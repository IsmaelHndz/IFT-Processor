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
PROJECT_DIR = '/home/ec2-user/IFT-Processor/telcel-project'
INPUT_CSV = os.path.join(PROJECT_DIR, 'numeros_recibidos.csv') # Archivo temporal para el CSV del correo
OUTPUT_CSV = os.path.join(PROJECT_DIR, 'results.csv') # El scraper lo genera en la raíz del proyecto
MAIN_SCRIPT = os.path.join(PROJECT_DIR, 'scraper-telcel.py')

S3_BUCKET_NAME = 'telcel-monitor-status' # Se pasa como variable de entorno

def limpiar_archivos_previos():
    """Elimina los archivos CSV de entrada y salida para evitar procesar datos antiguos."""
    if os.path.exists(INPUT_CSV):
        os.remove(INPUT_CSV)
        print(f"Archivo de entrada anterior eliminado: {INPUT_CSV}")
    if os.path.exists(OUTPUT_CSV):
        os.remove(OUTPUT_CSV)
        print(f"Archivo de resultados anterior eliminado: {OUTPUT_CSV}")

def procesar_y_responder():
    with IMAPClient(IMAP_HOST, ssl=True) as server:
        server.login(GMAIL_USER, GMAIL_APP_PASSWORD)
        server.select_folder('INBOX')
        print("Buscando correos no leídos con 'telcel' en el asunto...")
        messages = server.search(['UNSEEN', 'SUBJECT', 'telcel'])
        
        messages = messages[::-1]  # Procesa el más reciente primero
        if not messages:
            print("No hay correos nuevos que cumplan los criterios.")
            return

        for msgid in messages:
            print(f"Procesando mensaje ID: {msgid}")
            raw_message = server.fetch(msgid, ['RFC822'])[msgid][b'RFC822']
            message = pyzmail.PyzMessage.factory(raw_message)
            for part in message.mailparts:
                if part.filename and part.filename.lower().endswith('.csv'):
                    limpiar_archivos_previos()
                    # Guarda el adjunto en la ruta de entrada
                    try:
                        with open(INPUT_CSV, 'wb') as f:
                            f.write(part.get_payload())
                    except Exception as e:
                        print(f"ERROR: No se pudo guardar el adjunto CSV localmente: {e}")
                        continue
                        
                    subject = message.get_subject()
                    from_addr = message.get_addresses('from')[0][1]
                    print(f"Archivo CSV '{part.filename}' recibido de: {from_addr}. Iniciando scraper...")

                    # Pasar datos al scraper vía variables de entorno
                    os.environ['S3_BUCKET_NAME'] = S3_BUCKET_NAME
                    os.environ['EMAIL_FROM'] = from_addr
                    os.environ['EMAIL_SUBJECT'] = subject

                    # Ejecuta el script principal del scraper
                    os.chdir(PROJECT_DIR) # Asegurarse de estar en el directorio correcto
                    command = f'python3 {MAIN_SCRIPT} --csv {INPUT_CSV}'
                    print(f"Ejecutando comando: {command}")
                    exit_code = os.system(command)

                    status = "PROCESADO CON ÉXITO"

                    if exit_code != 0:
                        status = f"ERROR SCRAPER (código: {exit_code})"
                        print(f"Error ejecutando el script '{MAIN_SCRIPT}' (código de salida: {exit_code}).")
                        
                    # Verifica que el archivo de salida exista
                    if exit_code == 0 and not os.path.exists(OUTPUT_CSV):
                        status = "ERROR NO CSV DE SALIDA"
                        print("¡ERROR! No se generó el archivo de resultados.")
                        
                    # Envía el resultado por correo SOLO si no hubo error crítico del scraper
                    if status == "PROCESADO CON ÉXITO":
                        enviar_resultado(from_addr, subject)

                    # Marca como leído
                    server.add_flags(msgid, [b'\\Seen'])
                    print(f"Mensaje {msgid} procesado y marcado como leído.")

                    print("Esperando al siguiente ciclo.")
                    return  # Procesa solo un correo por ciclo para no sobrecargar

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
    print(f"Correo de resultados enviado a {to_email}.")

if __name__ == "__main__":
    print("Procesador automático iniciado. Pulsa Ctrl+C para detener.")
    while True:
        try:
            procesar_y_responder()
        except Exception as e:
            print(f"Error: {e}")
        time.sleep(60)  # Espera 1 minuto antes de revisar de nuevo