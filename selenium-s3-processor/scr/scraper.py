import time
import pandas as pd
from tenacity import retry, stop_after_attempt, wait_fixed
from rich.console import Console
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import (
    TimeoutException,
    StaleElementReferenceException,
    WebDriverException,
)
from selenium.webdriver.common.by import By

from .driver import get_driver
from .parser import (
    Loc,
    get_value,
    LBL_PROVEEDOR,
)

URL = (
    "https://sns.ift.org.mx:8081/sns-frontend/"
    "consulta-numeracion/numeracion-geografica.xhtml"
)

console = Console()

class IFTScraper:
    def __init__(
        self,
        infile: str = "data/input/numeros.csv",
        outfile: str = "data/output/resultados.csv",
        headless: bool = False,
        s3_client=None,
        bucket_name=None,
        logs_folder=None,
    ):
        self.infile = infile
        self.outfile = outfile
        self.driver = get_driver(headless=headless)
        self.wait = WebDriverWait(self.driver, 25)
        self.rows = []

    # Espera robusta a que la tabla desaparezca
    def _wait_table_disappear(self, timeout=10):
        for _ in range(timeout):
            try:
                tabla = self.driver.find_element(*Loc.TABLE)
                if not tabla.is_displayed():
                    return
            except Exception:
                return
            time.sleep(1)

    # Helper: leer celda con reintento (evita stale element)
    @retry(stop=stop_after_attempt(3), wait=wait_fixed(6))
    def _safe_get(self, label: str) -> str:
        try:
            return get_value(self.driver, label)
        except (StaleElementReferenceException, TimeoutException):
            # Ya no guardamos capturas ni logs
            raise

    # Espera robusta a que un botón pierda la clase 'ui-state-disabled'
    def _wait_button_enabled(self, locator, timeout=15):
        for _ in range(timeout):
            try:
                elem = self.driver.find_element(*locator)
                clases = elem.get_attribute("class")
                aria = elem.get_attribute("aria-disabled")
                if "ui-state-disabled" not in clases and aria == "false":
                    return True
            except Exception:
                pass
            time.sleep(1)
        raise Exception("El botón no se habilitó a tiempo.")

    # Hace clic usando JavaScript, siempre busca el botón justo antes del click
    def _safe_click(self, locator):
        elem = self.driver.find_element(*locator)
        self.driver.execute_script("arguments[0].click();", elem)

    # Procesa un solo número
    def _process_number(self, numero: str, retry_after_reset=False):
        try:
            input_box = self.wait.until(EC.element_to_be_clickable(Loc.INPUT))
            input_box.clear()
            input_box.send_keys(numero)

            self._wait_button_enabled(Loc.BTN_OK)
            self._safe_click(Loc.BTN_OK)

            self.wait.until(EC.visibility_of_element_located(Loc.TABLE))

            proveedor = self._safe_get(LBL_PROVEEDOR)

            console.print(f"[green]{numero}[/] ➜ {proveedor}")
            self.rows.append(
                dict(
                    telefono=numero,
                    proveedor=proveedor,
                )
            )

            self._wait_button_enabled(Loc.BTN_CLR)
            self._safe_click(Loc.BTN_CLR)

            self._wait_table_disappear()
            time.sleep(2)

        except TimeoutException:
            console.print(f"[red]{numero} ➜ ERROR:[/] Timeout esperando un elemento.")
            if not retry_after_reset:
                self._reset_page()
                self._process_number(numero, retry_after_reset=True)
            else:
                self.rows.append({"telefono": numero, "proveedor": "ERROR"})
        except StaleElementReferenceException:
            console.print(f"[red]{numero} ➜ ERROR:[/] Elemento obsoleto.")
            if not retry_after_reset:
                self._reset_page()
                self._process_number(numero, retry_after_reset=True)
            else:
                self.rows.append({"telefono": numero, "proveedor": "ERROR"})
        except WebDriverException as exc:
            console.print(f"[red]{numero} ➜ ERROR:[/] Error del navegador: {exc}")
            if not retry_after_reset:
                self._reset_page()
                self._process_number(numero, retry_after_reset=True)
            else:
                self.rows.append({"telefono": numero, "proveedor": "ERROR"})
        except Exception as exc:
            console.print(f"[red]{numero} ➜ ERROR:[/] {exc}")
            if not retry_after_reset:
                self._reset_page()
                self._process_number(numero, retry_after_reset=True)
            else:
                self.rows.append({"telefono": numero, "proveedor": "ERROR"})

    def _reset_page(self):
        console.print("[yellow]Reiniciando la página...[/]")
        self.driver.get(URL)
        time.sleep(10)

    def run(self):
        start_time = time.time()
        self.driver.get(URL)

        df = pd.read_csv(self.infile, dtype=str)
        total_numeros = len(df)

        for numero in df["telefono"].astype(str).str.strip():
            try:
                self._process_number(numero)
            except Exception as exc:
                console.print(f"[red]{numero} ➜ ERROR:[/] {exc}")
                self.rows.append({"telefono": numero, "proveedor": "ERROR"})

        self.driver.quit()
        pd.DataFrame(self.rows).to_csv(self.outfile, index=False)

        end_time = time.time()
        elapsed_time = end_time - start_time

        console.print(f"[bold cyan]Archivo generado:[/] {self.outfile}")
        console.print(f"[bold green]Tiempo total de ejecución:[/] {elapsed_time:.2f} segundos")
        console.print(f"[bold green]Cantidad de números procesados:[/] {total_numeros}")