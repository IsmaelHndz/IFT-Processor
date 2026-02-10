import argparse
import logging
import os
import time
from datetime import datetime
from typing import Optional
import sys

from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC # noqa
from selenium.common.exceptions import TimeoutException, WebDriverException
import csv
from pathlib import Path
from logging.handlers import RotatingFileHandler

try:
    import boto3
except ImportError:
    boto3 = None
try:
    from zoneinfo import ZoneInfo
except ImportError:
    ZoneInfo = None


# ----------------------
# Configuración / Constantes
# ----------------------
URL = "https://padnet.telcel.com/portal/"

# Selectores usados en la página
SELECTORS = {
    "popup_close": (By.CSS_SELECTOR, ".tc-modal__close"), # Botón para cerrar popup inicial
    "pay_button_home": (By.XPATH, "//button[contains(@class,'tc-home__card-button') and normalize-space(text())='Pagar']"),
    "input_number": (By.ID, "set-number-telcel-input"),
    "submit_number": (By.CSS_SELECTOR, "button[data-testid='qa_set-number_button']"),
}

# Timeouts (segundos)
DEFAULT_TIMEOUT = 20

# --- S3 Config (opcional, para status en tiempo real) ---
S3_BUCKET_NAME = os.environ.get("S3_BUCKET_NAME")
STATUS_FILE_PATH = Path("status.json")
HTML_STATUS_FILE_PATH = Path("index.html")


def configure_options(headless: bool = True) -> Options:
    """Configura y devuelve las opciones de Chrome."""
    options = Options()
    if headless:
        options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--window-size=1920,1080")
    options.add_argument(
        "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/98.0.4758.102 Safari/537.36"
    )
    return options


def create_driver(headless: bool = True) -> webdriver.Chrome:
    """Crea e inicializa el driver de Chrome usando webdriver_manager."""
    service = Service(ChromeDriverManager().install())
    return webdriver.Chrome(service=service, options=configure_options(headless))


RESULTS_CSV = "results.csv"


def save_result_row(telefono: str, status: str) -> None:
    """Guarda una fila en el CSV de resultados (telefono, status)."""
    header = ["telefono", "status"]
    try:
        with open(RESULTS_CSV, "a", newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            if f.tell() == 0:
                writer.writerow(header)
            writer.writerow([telefono, status])
        logging.debug("Resultado guardado en %s: %s %s", RESULTS_CSV, telefono, status)
    except Exception:
        logging.exception("No se pudo guardar la fila de resultado para %s", telefono)


def close_popup(driver: webdriver.Chrome, timeout: int = DEFAULT_TIMEOUT) -> bool:
    """Intenta cerrar un pop-up si aparece. Devuelve True si cerró algo."""
    try:
        logging.debug("Buscando pop-up con selector: %s", SELECTORS["popup_close"]) 
        close_btn = WebDriverWait(driver, timeout).until(
            EC.element_to_be_clickable(SELECTORS["popup_close"])
        )
        logging.debug("Pop-up encontrado, cerrando...")
        close_btn.click()
        time.sleep(0.5) # Espera para animación
        logging.debug("Pop-up cerrado.")
        return True
    except TimeoutException:
        logging.debug("No se encontró pop-up dentro de %ss", timeout)
        return False
    except Exception:
        logging.exception("Error cerrando el pop-up")
        return False


def click_pay_button(driver: webdriver.Chrome, timeout: int = DEFAULT_TIMEOUT) -> Optional[str]:
    """Hace clic en el botón 'Pagar' y espera a que la URL cambie."""
    original_url = driver.current_url
    logging.debug("Buscando botón 'Pagar' en la home...")

    # Lista de estrategias para encontrar y hacer clic en el botón
    strategies = [
        # 1. Selector XPath principal (más robusto)
        lambda: WebDriverWait(driver, min(timeout, 5)).until(EC.element_to_be_clickable(SELECTORS["pay_button_home"])),
        # 2. JS para encontrar el tercer botón con la clase (fallback específico)
        lambda: driver.execute_script("return document.querySelectorAll('button.tc-home__card-button')[2];"),
        # 3. JS para encontrar cualquier botón que contenga "Pagar" (fallback general)
        lambda: driver.execute_script("return Array.from(document.querySelectorAll('button')).find(b => b.textContent && b.textContent.trim().toLowerCase().includes('pagar'));")
    ]

    for i, strategy in enumerate(strategies):
        try:
            pay_btn = strategy()
            if pay_btn:
                logging.debug("Estrategia #%d encontró un botón. Intentando click...", i + 1)
                driver.execute_script("arguments[0].scrollIntoView(true); arguments[0].click();", pay_btn)
                
                WebDriverWait(driver, timeout).until(EC.url_changes(original_url))
                new_url = driver.current_url
                logging.debug("Navegación detectada. Nueva URL: %s", new_url)
                return new_url
        except Exception as e:
            logging.debug("Estrategia #%d falló: %s", i + 1, str(e).split('\n')[0])

    logging.error("No se pudo localizar ni clickear el botón 'Pagar' con ninguna estrategia.")
    return None


def fill_number_and_submit(driver: webdriver.Chrome, number: str, timeout: int = DEFAULT_TIMEOUT) -> bool:
    """Rellena el número y hace click en el botón 'Pagar' del formulario."""
    try:
        logging.debug("Rellenando número: %s", number)
        input_el = find_element_across_frames(driver, SELECTORS["input_number"], timeout=timeout)
        if input_el is None:
            logging.error("fill_number_and_submit: no se encontró input para %s", number)
            return False
        try:
            input_el.clear()
        except Exception:
            logging.debug("input.clear() falló, intentando establecer valor por JS")
            try:
                driver.execute_script("arguments[0].value = ''", input_el)
            except Exception:
                logging.exception("No se pudo limpiar el input por JS")
        input_el.send_keys(number)
        logging.debug("Valor enviado al input (intento): %s", number)

        submit_btn = find_element_across_frames(driver, SELECTORS["submit_number"], timeout=timeout)
        if submit_btn is None:
            logging.error("fill_number_and_submit: no se encontró botón submit para %s", number)
            return False
        logging.debug("Haciendo click en botón de pagar factura para %s", number)
        submit_btn.click()
        logging.debug("Click realizado para %s.", number)
        return True
    except TimeoutException:
        logging.exception("Timeout al intentar rellenar o enviar el número: %s", number)
        return False
    except Exception:
        logging.exception("Error inesperado al enviar el número: %s", number)
        return False


def read_numbers_from_csv(csv_path: Path) -> list:
    """Lee una columna 'telefono' desde un CSV y devuelve la lista de números."""
    numbers = []
    # Usar 'utf-8-sig' para manejar el BOM (Byte Order Mark) que algunos programas añaden
    with csv_path.open(newline='', encoding='utf-8-sig') as f:
        # Usar Sniffer para detectar el dialecto del CSV (delimitador, etc.)
        try:
            dialect = csv.Sniffer().sniff(f.read(1024))
            f.seek(0)
            reader = csv.reader(f, dialect)
        except csv.Error:
            logging.warning("No se pudo detectar el dialecto del CSV, usando valores por defecto.")
            f.seek(0)
            reader = csv.reader(f)

        header = next(reader, None) # Leer la primera fila como encabezado
        phone_index = -1
        if header:
            try:
                # Buscar 'telefono' insensible a mayúsculas/minúsculas
                phone_index = [h.lower().strip() for h in header].index('telefono')
            except ValueError:
                logging.warning("No se encontró la columna 'telefono'. Se usará la primera columna.")
                phone_index = 0
        
        # Si no hay encabezado o no se encontró 'telefono', se asume la primera columna (índice 0)
        if phone_index == -1: phone_index = 0

        # Volver al inicio si ya leímos el encabezado para procesar todas las filas
        f.seek(0)
        # Omitir el encabezado para la lectura de datos
        next(reader, None)

        for row in reader:
            if row and len(row) > phone_index:
                val = row[phone_index]
                if val and val.strip():
                    numbers.append(val.strip())
    return numbers


def handle_uncaught_exception(exc_type, exc_value, exc_traceback):
    """Handler para excepciones no capturadas: las manda al logger y guarda captura si hay driver."""
    if issubclass(exc_type, KeyboardInterrupt):
        # mantiene el comportamiento por defecto para Ctrl-C
        sys.__excepthook__(exc_type, exc_value, exc_traceback)


def find_element_across_frames(driver: webdriver.Chrome, locator: tuple, timeout: int = 3):
    """Busca un elemento en el documento principal y en los iframes.

    Devuelve el elemento si lo encuentra (y deja el frame activo donde se encontró),
    o None si no lo encuentra.
    """
    # 1) Intentar en el contexto principal
    try:
        return WebDriverWait(driver, timeout).until(EC.presence_of_element_located(locator))
    except Exception:
        pass

    # 2) Intentar en cada iframe
    frames = driver.find_elements(By.TAG_NAME, "iframe")
    for i, frame in enumerate(frames):
        try:
            driver.switch_to.frame(frame)
            try:
                el = WebDriverWait(driver, timeout).until(EC.presence_of_element_located(locator))
                return el
            except Exception:
                # no encontrado en este frame
                driver.switch_to.default_content()
                continue
        except Exception:
            driver.switch_to.default_content()
            continue

    # dejar el contexto principal
    try:
        driver.switch_to.default_content()
    except Exception:
        pass
    return None


def wait_for_payment_page(driver: webdriver.Chrome, timeout: int = DEFAULT_TIMEOUT) -> bool:
    """Espera a que la URL de la página contenga '/ps/home/' (página de pago con token).

    Devuelve True si detecta la URL, False en timeout.
    """
    try:
        logging.debug("Esperando URL de página de pago ('/ps/home/')...")
        WebDriverWait(driver, timeout).until(lambda d: '/ps/home/' in (d.current_url or ''))
        logging.debug("Página de pago detectada: %s", driver.current_url)
        return True
    except TimeoutException:
        logging.warning("No se detectó la URL de página de pago en %s segundos. URL actual: %s", timeout, driver.current_url)
        try:
            logging.info("HTML de la página actual guardado en logs/debug_payment_page.html")
            (Path("logs") / "debug_payment_page.html").write_text(driver.page_source, encoding='utf-8')
        except Exception:
            logging.exception("No se pudo guardar el HTML de depuración.")
        return False
    except Exception:
        logging.exception("Error inesperado esperando la página de pago")
        return False


def wait_for_result(driver: webdriver.Chrome, timeout: int = 20, poll: float = 0.5) -> tuple[str, Optional[str]]:
    """Polling activo para detectar rápidamente el resultado tras enviar un número.

    Devuelve una tupla (status, detalle).
    """
    logging.debug("Polling para resultado (timeout=%s, poll=%s)...", timeout, poll)
    start = time.time()

    # Casos a comprobar en cada iteración del polling
    cases = {
        "RECARGAS": lambda d: d.current_url.rstrip('/') == URL.rstrip('/') or d.title.strip().lower() == 'recargas telcel',
        "SUCCESS": (By.CSS_SELECTOR, "p[data-testid='qa_success_amount']"),
        "PAGADO": (By.CSS_SELECTOR, "p.success__text"),
        "NO SUCEPTIBLE": (By.CSS_SELECTOR, "p[data-testid='qa_denied_error-message']"),
        "BAJA": (By.CSS_SELECTOR, "p[data-testid='input-error-qa_set-number_input']"),
    }

    while time.time() - start < timeout:
        try:
            for status, check in cases.items():
                if callable(check): # Para 'RECARGAS'
                    if check(driver):
                        logging.debug("Detectado %s por URL/title", status)
                        return (status, None)
                else: # Para selectores
                    el = find_element_across_frames(driver, check, timeout=0.1)
                    if el:
                        txt = el.text.strip()
                        logging.debug("Detectado %s: %s", status, txt[:100])
                        return (status, txt)
        except Exception:
            logging.exception("Error durante polling de resultado")
        time.sleep(poll)
    logging.warning("wait_for_result: timeout sin detectar resultado en %s segundos", timeout)
    return ("TIMEOUT", None)


def update_s3_status(status_data: dict, results_csv_path: str) -> None:
    """
    Genera un HTML de estado y sube status.json, index.html y results.csv a S3.
    Esta función es llamada por el scraper después de procesar cada número.
    """
    if not boto3 or not S3_BUCKET_NAME:
        logging.debug("Boto3 no instalado o S3_BUCKET_NAME no configurado. Saltando actualización de S3.")
        return

    # 1. Contar resultados en el CSV
    result_lines = 0
    try:
        if Path(results_csv_path).exists():
            with open(results_csv_path, 'r', encoding='utf-8') as f:
                result_lines = len(f.readlines()) - 1  # No contar el header
            if result_lines < 0:
                result_lines = 0
    except Exception as e:
        logging.warning("No se pudo leer el número de líneas de results.csv: %s", e)
        result_lines = "ERROR"

    # 2. Guardar status.json localmente
    try:
        STATUS_FILE_PATH.write_text(str(status_data), encoding='utf-8')
    except Exception as e:
        logging.error("No se pudo escribir el status.json local: %s", e)
        return # No continuar si no podemos ni escribir el JSON

    # Obtener hora actual en la zona horaria de México
    if ZoneInfo:
        mx_tz = ZoneInfo("America/Mexico_City")
        now_str = datetime.now(tz=mx_tz).strftime('%Y-%m-%d %H:%M:%S %Z')
    else:
        now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S (sin zona horaria)')

    # 3. Generar HTML
    html_content = f"""
    <!DOCTYPE html>
    <html lang="es">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Monitor de Scraper Telcel</title>
        <meta http-equiv="refresh" content="15">
        <style>
            body {{ 
                font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; 
                background-color: #121212; 
                color: #e0e0e0; 
                margin: 20px; 
            }}
            .container {{ 
                max-width: 800px; 
                margin: auto; 
                background: #1e1e1e; 
                padding: 25px; 
                border-radius: 12px; 
                box-shadow: 0 4px 20px rgba(0,0,0,0.5);
                border: 1px solid #333;
            }}
            h1 {{ color: #64b5f6; }}
            p {{ color: #bdbdbd; }}
            .status-grid {{ display: grid; grid-template-columns: 150px 1fr; gap: 12px; margin-top: 25px; align-items: center; }}
            .label {{ font-weight: bold; color: #82aaff; }}
            .value {{ background: #2a2a2a; color: #e0e0e0; padding: 8px 12px; border-radius: 6px; }}
            .progress-bar-container {{ background: #333; border-radius: 8px; overflow: hidden; margin: 25px 0; }}
            .progress-bar {{ height: 24px; background: #009688; width: {status_data.get('progress', 0)}%; color: white; text-align: center; line-height: 24px; font-weight: bold; transition: width 0.5s ease-in-out; }}
            a {{ color: #64b5f6; text-decoration: none; font-weight: bold; }}
            a:hover {{ color: #90caf9; text-decoration: underline; }}
        </style>
    </head>
    <body>
        <div class="container">
            <h1>🚀 Monitor de Procesamiento Telcel</h1>
            <p>Última actualización: {now_str}</p>
            
            <div class="progress-bar-container">
                <div class="progress-bar">{status_data.get('progress', 0)}%</div>
            </div>

            <div class="status-grid">
                <div class="label">Estado:</div><div class="value">{status_data.get('status', 'N/A')}</div>
                <div class="label">Asunto:</div><div class="value">{status_data.get('email_subject', 'N/A')}</div>
                <div class="label">Total a procesar:</div><div class="value">{status_data.get('total_numbers', 'N/A')}</div>
                <div class="label">Procesados:</div><div class="value">{status_data.get('processed_count', 'N/A')}</div>
                <div class="label">Descargar:</div><div class="value"><a href="results.csv" download>results.csv</a></div>
            </div>
        </div>
    </body>
    </html>
    """
    HTML_STATUS_FILE_PATH.write_text(html_content, encoding='utf-8')

    # 4. Subir a S3
    try:
        s3 = boto3.client('s3')
        s3.upload_file(str(STATUS_FILE_PATH), S3_BUCKET_NAME, 'status.json', ExtraArgs={'ContentType': 'application/json', 'CacheControl': 'no-cache'})
        s3.upload_file(str(HTML_STATUS_FILE_PATH), S3_BUCKET_NAME, 'index.html', ExtraArgs={'ContentType': 'text/html', 'CacheControl': 'no-cache'})
        if Path(results_csv_path).exists():
            s3.upload_file(results_csv_path, S3_BUCKET_NAME, 'results.csv', ExtraArgs={'ContentType': 'text/csv', 'CacheControl': 'no-cache'})
        logging.info("Estado actualizado en S3 bucket: %s", S3_BUCKET_NAME)
    except Exception as e:
        logging.error("No se pudieron subir los archivos a S3: %s", e)


def main(headless: bool = True, timeout: int = DEFAULT_TIMEOUT, numbers: Optional[list] = None, result_timeout: int = 20, result_poll: float = 0.5) -> int:
    """Función principal que coordina el scraping."""

    failures = 0
    stats = {
        'total': 0,
        'by_status': {},
        'times': [],
    }
    driver = None # Inicializar driver a None
    try:
        if numbers is None:
            driver = create_driver(headless=headless)
            logging.info("Abriendo URL: %s", URL)
            driver.get(URL)

            # Intentar cerrar pop-up si existe
            close_popup(driver, timeout=timeout)

            # Hacer click en pagar (comportamiento original)
            new_url = click_pay_button(driver, timeout=timeout)
            if not new_url:
                return 3 # Código de error específico

            logging.info("Flujo sin CSV completado.")
            logging.info("Título de la página: %s", driver.title)
            return 0

        # Si recibimos una lista de números, procesarlos en la misma sesión
        logging.info("Procesando %s números en una sola sesión", len(numbers))

        # --- Status para S3 ---
        total_numbers = len(numbers)
        status_payload = {
            "status": "RUNNING",
            "total_numbers": total_numbers,
            "processed_count": 0,
            "progress": 0,
            "email_from": os.environ.get("EMAIL_FROM", "N/A"),
            "email_subject": os.environ.get("EMAIL_SUBJECT", "N/A"),
        }
        for i, number in enumerate(numbers):
            try:
                stats['total'] += 1 # noqa
                number_start = time.time()

                # (RECOMENDACIÓN) Crear un driver nuevo en cada iteración para máxima robustez
                # o al menos, crearlo si no existe o ha fallado.
                if driver is None:
                    logging.info(f"Iniciando driver para {number}...")
                    logging.info("Iniciando nueva instancia de driver...")
                    driver = create_driver(headless=headless)

                # 1) Cargar la página principal
                driver.get(URL)

                # 2) Cerrar popup si aparece
                close_popup(driver, timeout=timeout)

                # 3) Click en el botón 'Pagar' de la home y esperar navegación
                new_url = click_pay_button(driver, timeout=timeout)
                if not new_url:
                    logging.error("No se pudo navegar desde la home para %s", number)
                    failures += 1
                    continue

                # 3b) Esperar que la URL de la página de pago con token aparezca (/ps/home/)
                if not wait_for_payment_page(driver, timeout=timeout):
                    logging.error("No se alcanzó la página de pago para %s", number)
                    failures += 1
                    continue

                # 4) En la página de pago, esperar que aparezca el input y el botón
                try:
                    if not find_element_across_frames(driver, SELECTORS["input_number"], timeout=timeout) or \
                       not find_element_across_frames(driver, SELECTORS["submit_number"], timeout=timeout):
                        logging.error("No se encontraron los elementos de formulario en la página de pago para %s", number)
                        failures += 1
                        continue
                except Exception:
                    logging.exception("Error buscando elementos de formulario para %s", number)
                    failures += 1
                    continue

                # 5) Rellenar número y enviar
                ok = fill_number_and_submit(driver, number, timeout=timeout)
                if not ok:
                    failures += 1
                    continue

                # Comprobar si tras el submit la app nos redirige de nuevo a la home.
                try:
                    # Hacer polling durante result_timeout con interval result_poll
                    elapsed = 0.0
                    found_home = False
                    while elapsed < result_timeout:
                        current_after_submit = driver.current_url # noqa
                        logging.debug("Polling URL tras submit (%.1fs): %s", elapsed, current_after_submit)
                        if current_after_submit.rstrip('/') == URL.rstrip('/') or driver.title.strip().lower() == 'recargas telcel':
                            logging.info("Tras submit la URL volvió a la home (poll): RECARGAS para %s", number)
                            save_result_row(number, "RECARGAS")
                            found_home = True
                            break
                        time.sleep(result_poll)
                        elapsed += result_poll
                    if found_home:
                        continue
                except Exception:
                    logging.exception("Error comprobando URL tras submit para %s", number)

                # 6) Esperar cambio de estado/resultado
                try:
                    # Usar polling activo y específico para detectar el resultado lo antes posible
                    status, detail = wait_for_result(driver, timeout=result_timeout, poll=result_poll)
                    logging.debug("Resultado para %s: %s (detalle: %s)", number, status, detail is not None)
                    elapsed = time.time() - number_start
                    stats['times'].append(elapsed)
 
                    def bump(status_key):
                        stats['by_status'][status_key] = stats['by_status'].get(status_key, 0) + 1
 
                    # Procesar cada caso y asegurar que siempre se continúe
                    if status == "RECARGAS":
                        save_result_row(number, "RECARGAS")
                        bump("RECARGAS")
                    elif status == "SUCCESS":
                        save_result_row(number, detail or "SUCCESS")
                        bump("SUCCESS")
                    elif status == "PAGADO":
                        save_result_row(number, "PAGADO")
                        bump("PAGADO")
                    elif status == "NO SUCEPTIBLE":
                        save_result_row(number, "NO SUCEPTIBLE")
                        bump("NO_SUCEPTIBLE")
                    elif status == "BAJA":
                        save_result_row(number, "BAJA")
                        bump("BAJA")
                    elif status == "TIMEOUT":
                        save_result_row(number, "N/A")
                        bump("TIMEOUT")
                        logging.warning("Timeout procesando %s, continuando con siguiente número", number)
                    else:
                        logging.warning("Resultado no manejado para %s: %s", number, status)
                        save_result_row(number, f"UNHANDLED_{status}")
                        bump("UNHANDLED")
 
                    logging.debug("Procesado %s en %.2fs -> %s", number, elapsed, status)
 
                    # --- Actualizar estado para S3 ---
                    status_payload["processed_count"] = i + 1
                    status_payload["progress"] = round(((i + 1) / total_numbers) * 100)
                    status_payload["last_processed_number"] = number
                    status_payload["last_status"] = status
                    update_s3_status(status_payload, RESULTS_CSV)
 
                except Exception as e:
                    # Asegurar que incluso si hay un error, se guarde algo y se continúe
                    logging.exception("Error esperando el resultado para %s", number)
                    save_result_row(number, "ERROR")
                    stats['by_status']["ERROR"] = stats['by_status'].get("ERROR", 0) + 1
                    # NO hacer return ni raise, solo continuar
 
            except Exception as e:
                # Error general procesando el número
                logging.exception("Error procesando número: %s", number)
                save_result_row(number, "ERROR_GENERAL")
                failures += 1
                # IMPORTANTE: No hacer break ni return, el continue está implícito

        if failures:
            logging.warning("Procesamiento finalizado con %s fallos", failures)

        # Actualizar el conteo y progreso al valor final antes de marcar como completado
        status_payload["processed_count"] = total_numbers
        status_payload["progress"] = 100

        status_payload["status"] = "COMPLETED" if failures == 0 else "COMPLETED_WITH_ERRORS"
        update_s3_status(status_payload, RESULTS_CSV)

        # Resumen de métricas
        try:
            total = stats.get('total', 0)
            avg_time = sum(stats.get('times', [])) / len(stats.get('times', [])) if stats.get('times') else 0
            logging.info("Resumen final: %s procesados en %.2fs/número. Desglose: %s", total, avg_time, stats.get('by_status'))
        except Exception: # noqa
            logging.exception("Error generando resumen de métricas")
        return 0 if failures == 0 else 6

    except Exception:
        logging.exception("Error inesperado durante la ejecución")
        return 1

    finally:
        try:
            if driver:
                driver.quit()
                logging.info("Driver cerrado correctamente.")
        except Exception:
            logging.exception("Error al cerrar el driver")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Scraper para portal Telcel - extraer flujo de pago")
    parser.add_argument("--no-headless", dest="headless", action="store_false", help="Ejecutar con interfaz (no headless)")
    parser.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT, help="Timeout en segundos para esperas")
    parser.add_argument("--csv", type=str, default=None, help="Ruta a CSV con columna 'telefono' para procesar")
    parser.add_argument("--result-timeout", type=int, default=20, help="Timeout en segundos para esperar el resultado tras enviar número")
    parser.add_argument("--result-poll", type=float, default=0.5, help="Intervalo de polling (s) para esperar el resultado")
    parser.add_argument("--verbose", "-v", action="count", default=0, help="Verbosity (-v, -vv)")
    args = parser.parse_args()

    # Configurar logging
    level = logging.INFO
    if args.verbose == 1:
        level = logging.INFO
    elif args.verbose >= 2:
        level = logging.DEBUG

    logging.basicConfig(level=level, format="%(asctime)s [%(levelname)s] %(message)s")

    # Configurar handler a fichero con rotación
    logs_dir = Path("logs")
    logs_dir.mkdir(exist_ok=True)
    file_handler = RotatingFileHandler(logs_dir / "scraper.log", maxBytes=5_000_000, backupCount=3, encoding="utf-8")
    file_handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
    logging.getLogger().addHandler(file_handler)

    # Instalar handler para excepciones no capturadas
    sys.excepthook = handle_uncaught_exception

    # Si se pasó CSV, leer números y pasarlos a main para procesarlos en una sola sesión
    numbers = None
    if args.csv:
        csv_path = Path(args.csv)
        if not csv_path.exists():
            logging.error("CSV no encontrado: %s", csv_path)
            raise SystemExit(4)

        try:
            numbers = read_numbers_from_csv(csv_path)
        except Exception as e:
            logging.exception("No se pudo leer el CSV: %s", e)
            raise SystemExit(5)

    exit_code = main(
        headless=args.headless,
        timeout=args.timeout,
        numbers=numbers,
        result_timeout=args.result_timeout,
        result_poll=args.result_poll,
    )
    raise SystemExit(exit_code)