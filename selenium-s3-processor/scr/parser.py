# scr/parser.py
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

# --- IDs fijo que expusiste al inspeccionar la página ---------------
INPUT_ID  = "FORM_myform:TXT_NationalNumber"
BTN_OK_ID = "FORM_myform:BTN_publicSearch"
BTN_CLR_ID = "FORM_myform:LINK_CLEAR"
TABLE_ID   = "FORM_myform:TBL_numberInfoTable_content"   # contenedor de la tabla

class Loc:
    INPUT    = (By.ID, INPUT_ID)
    BTN_OK   = (By.ID, BTN_OK_ID)
    BTN_CLR  = (By.ID, BTN_CLR_ID)
    TABLE    = (By.ID, TABLE_ID)   # lo usamos solo para esperar que la tabla exista

# Etiquetas de la primera columna dentro de la tabla
LBL_PROVEEDOR = "Proveedor que atiende el número."
LBL_ENTIDAD   = "Zona a la que pertenece"
LBL_TIPO      = "Tipo de red y modalidad"

# -------------------------------------------------------------------
def _value_xpath(label_text: str) -> str:
    """
    Construye el XPath que, partiendo del <div> con el texto de la etiqueta,
    toma el <div> hermano que contiene el valor.
    """
    return (f"//div[@id='{TABLE_ID}']"
            f"//div[text()='{label_text}']/following-sibling::div[1]")

def get_value(driver, label_text: str, timeout: int = 20) -> str:
    """
    Espera a que exista la celda de valor para la etiqueta dada y devuelve su texto.
    """
    xp = _value_xpath(label_text)
    return WebDriverWait(driver, timeout).until(
        EC.visibility_of_element_located((By.XPATH, xp))
    ).text.strip()