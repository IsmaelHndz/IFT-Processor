from selenium import webdriver
from selenium.webdriver.chrome.options import Options

def get_driver(headless=True):
    chrome_options = Options()
    if headless:
        chrome_options.add_argument("--headless")  # Ejecutar en modo headless
    chrome_options.add_argument("--no-sandbox")  # Requerido para entornos sin privilegios
    chrome_options.add_argument("--disable-dev-shm-usage")  # Evitar problemas de memoria compartida
    chrome_options.add_argument("--disable-gpu")  # Opcional, pero recomendado en headless
    chrome_options.add_argument("--window-size=1920x1080")  # Opcional, tamaño de ventana predeterminado
    chrome_options.add_argument("--disable-extensions")  # Deshabilitar extensiones para evitar conflictos

    return webdriver.Chrome(options=chrome_options)