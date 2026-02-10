import time
import os
from imapclient import IMAPClient
import pyzmail
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.application import MIMEApplication

# Configuración de Gmail
GMAIL_USER = 'web.scraper.ift@gmail.com'
GMAIL_APP_PASSWORD = 'lpdgsqfabbtlnmdg'
IMAP_HOST = 'imap.gmail.com'
SMTP_HOST = 'smtp.gmail.com'
SMTP_PORT = 587

# Rutas absolutas de tu proyecto
PROJECT_DIR = '/home/ec2-user/selenium-s3-processor'
INPUT_CSV = os.path.join(PROJECT_DIR, 'data/input/numeros.csv')
OUTPUT_CSV = os.path.join(PROJECT_DIR, 'data/output/resultados.csv')
MAIN_SCRIPT = os.path.join(PROJECT_DIR, 'main-direct.py')

def procesar_y_responder():
    with IMAPClient(IMAP_HOST, ssl=True) as server:
        server.login(GMAIL_USER, GMAIL_APP_PASSWORD)
        server.select_folder('INBOX')
        messages = server.search([
        'UNSEEN',
        'NOT', 'SUBJECT', 'Telcel'
        ])
        messages = messages[::-1]  # Procesa el más reciente primero
        for msgid in messages:
            raw_message = server.fetch(msgid, ['RFC822'])[msgid][b'RFC822']
            message = pyzmail.PyzMessage.factory(raw_message)
            for part in message.mailparts:
                if part.filename and part.filename.lower().endswith('.csv'):
                    # Guarda el adjunto como INPUT_CSV
                    os.makedirs(os.path.dirname(INPUT_CSV), exist_ok=True)
                    with open(INPUT_CSV, 'wb') as f:
                        f.write(part.get_payload())
                    subject = message.get_subject()
                    from_addr = message.get_addresses('from')[0][1]
                    print(f"Procesando archivo de: {from_addr}")

                    # Cambia el directorio antes de ejecutar el main
                    os.chdir(PROJECT_DIR)
                    exit_code = os.system('python3 main-direct.py')
                    if exit_code != 0:
                        print("Error ejecutando el main-direct.py")
                        continue

                    # Verifica que el archivo de salida exista
                    if not os.path.exists(OUTPUT_CSV):
                        print("¡ERROR! No se generó el archivo de resultados.")
                        continue

                    # Envía el resultado
                    enviar_resultado(from_addr, subject)
                    # Marca como leído
                    server.add_flags(msgid, [b'\\Seen'])
                    return  # Procesa solo uno por ciclo
        print("No hay correos nuevos con adjunto CSV.")

def enviar_resultado(to_email, original_subject):
    msg = MIMEMultipart()
    msg['From'] = GMAIL_USER
    msg['To'] = to_email
    msg['Subject'] = f"Resultados de tu archivo - {original_subject}"

    body = MIMEText("Adjunto encontrarás el archivo procesado.\n\n¡Gracias por usar el servicio!", 'plain')
    msg.attach(body)

    with open(OUTPUT_CSV, 'rb') as f:
        part = MIMEApplication(f.read(), Name=os.path.basename(OUTPUT_CSV))
        part['Content-Disposition'] = f'attachment; filename="{os.path.basename(OUTPUT_CSV)}"'
        msg.attach(part)

    with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
        server.starttls()
        server.login(GMAIL_USER, GMAIL_APP_PASSWORD)
        server.send_message(msg)
    print(f"Correo enviado a {to_email} con el resultado.")

if __name__ == "__main__":
    print("Procesador automático iniciado. Pulsa Ctrl+C para detener.")
    while True:
        try:
            procesar_y_responder()
        except Exception as e:
            print(f"Error: {e}")
        time.sleep(60)  # Espera 1 minuto antes de revisar de nuevo