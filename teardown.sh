#!/bin/bash
BUCKET_NAME="mis-eventos-fotos"
RDS_INSTANCE_ID="eventos-db"
SECRET_ID="prod/eventos/db"
EC2_INSTANCE_ID="i-05e23ab1f5f21af47"


echo "Eliminando bucket S3: $BUCKET_NAME..."
aws s3 rm s3://$BUCKET_NAME --recursive
aws s3 rb s3://$BUCKET_NAME

echo "Eliminando base de datos RDS: $RDS_INSTANCE_ID..."
aws rds delete-db-instance \
    --db-instance-identifier $RDS_INSTANCE_ID \
    --skip-final-snapshot

echo "Eliminando Secreto: $SECRET_ID..."
aws secretsmanager delete-secret \
    --secret-id $SECRET_ID \
    --force-delete-without-recovery

echo "Terminando instancia EC2: $EC2_INSTANCE_ID..."
aws ec2 terminate-instances --instance-ids $EC2_INSTANCE_ID

echo "Comandos de destrucción enviados a AWS exitosamente."