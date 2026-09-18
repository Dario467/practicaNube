from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.responses import StreamingResponse
import boto3
import json
import psycopg2
from psycopg2.extras import RealDictCursor
import uuid
import io
import zipfile
from PIL import Image, ImageDraw, ImageFont

app = FastAPI(title="Eventos Fotográficos API")

REGION_NAME = "us-east-1"
SECRET_NAME = "prod/eventos/db"
BUCKET_NAME = "mis-eventos-fotos"

secrets_client = boto3.client('secretsmanager', region_name=REGION_NAME)
s3_client = boto3.client('s3', region_name=REGION_NAME)


def get_db_connection():
    response = secrets_client.get_secret_value(SecretId=SECRET_NAME)
    secret = json.loads(response['SecretString'])

    conn = psycopg2.connect(
        host=secret['host'],
        port=secret['port'],
        user=secret['username'],
        password=secret['password'],
        dbname=secret['dbname']
    )
    return conn


def init_db():
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS events (
            id VARCHAR(36) PRIMARY KEY,
            client_name VARCHAR(100),
            event_type VARCHAR(50),
            event_date DATE
        );
        CREATE TABLE IF NOT EXISTS photos (
            id VARCHAR(36) PRIMARY KEY,
            event_id VARCHAR(36) REFERENCES events(id),
            message TEXT,
            original_s3_key VARCHAR(255),
            polaroid_s3_key VARCHAR(255)
        );
    """)
    conn.commit()
    cur.close()
    conn.close()


init_db()


@app.post("/events")
def create_event(client_name: str = Form(...), event_type: str = Form(...), event_date: str = Form(...)):
    event_id = str(uuid.uuid4())
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO events (id, client_name, event_type, event_date) VALUES (%s, %s, %s, %s)",
        (event_id, client_name, event_type, event_date)
    )
    conn.commit()
    cur.close()
    conn.close()
    return {"event_id": event_id, "message": "Evento creado exitosamente"}


@app.post("/upload")
async def upload_photo(event_id: str = Form(...), message: str = Form(...), file: UploadFile = File(...)):
    image_data = await file.read()
    img = Image.open(io.BytesIO(image_data)).convert("RGB")

    img_resized = img.resize((128, 128))
    original_buffer = io.BytesIO()
    img_resized.save(original_buffer, format="JPEG")
    original_buffer.seek(0)

    photo_id = str(uuid.uuid4())
    original_key = f"pictures/{photo_id}.jpg"

    s3_client.upload_fileobj(original_buffer, BUCKET_NAME, original_key)

    polaroid = Image.new('RGB', (148, 178), 'white')
    polaroid.paste(img_resized, (10, 10))

    draw = ImageDraw.Draw(polaroid)
    font = ImageFont.load_default()
    draw.text((10, 145), message, fill="black", font=font)

    polaroid_buffer = io.BytesIO()
    polaroid.save(polaroid_buffer, format="JPEG")
    polaroid_buffer.seek(0)

    polaroid_key = f"polaroids/{photo_id}.jpg"


    s3_client.upload_fileobj(polaroid_buffer, BUCKET_NAME, polaroid_key)


    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO photos (id, event_id, message, original_s3_key, polaroid_s3_key) VALUES (%s, %s, %s, %s, %s)",
        (photo_id, event_id, message, original_key, polaroid_key)
    )
    conn.commit()
    cur.close()
    conn.close()

    return {"photo_id": photo_id, "message": "Foto procesada y guardada"}


@app.get("/events/{event_id}")
def get_event(event_id: str):
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)

    cur.execute("SELECT * FROM events WHERE id = %s", (event_id,))
    event = cur.fetchone()
    if not event:
        raise HTTPException(status_code=404, detail="Evento no encontrado")

    cur.execute("SELECT count(*) as count FROM photos WHERE event_id = %s", (event_id,))
    photo_count = cur.fetchone()['count']

    cur.close()
    conn.close()

    event['photo_count'] = photo_count
    event['event_date'] = str(event['event_date'])
    return event


@app.post("/finish")
def finish_event(event_id: str = Form(...)):
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("SELECT polaroid_s3_key FROM photos WHERE event_id = %s", (event_id,))
    photos = cur.fetchall()
    cur.close()
    conn.close()

    if not photos:
        raise HTTPException(status_code=404, detail="No hay fotos para este evento")

    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zip_file:
        for index, photo in enumerate(photos):
            key = photo['polaroid_s3_key']
            file_obj = s3_client.get_object(Bucket=BUCKET_NAME, Key=key)
            file_content = file_obj['Body'].read()
            zip_file.writestr(f"polaroid_{index}.jpg", file_content)

    zip_buffer.seek(0)

    return StreamingResponse(
        zip_buffer,
        media_type="application/zip",
        headers={"Content-Disposition": f"attachment; filename=evento_{event_id}.zip"}
    )