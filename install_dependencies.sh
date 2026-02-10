
#!/bin/bash

# Actualizar sistema
echo "Actualizando sistema..."
sudo apt-get update && sudo apt-get upgrade -y

# Instalar Python3 y pip si no están
echo "Instalando Python3 y dependencias..."
sudo apt-get install -y python3 python3-pip python3-venv unzip curl wget

# Para Selenium/Chrome (Headless)
echo "Instalando Google Chrome..."
wget -q -O - https://dl-ssl.google.com/linux/linux_signing_key.pub | sudo apt-key add -
sudo sh -c 'echo "deb [arch=amd64] http://dl.google.com/linux/chrome/deb/ stable main" >> /etc/apt/sources.list.d/google-chrome.list'
sudo apt-get update
sudo apt-get install -y google-chrome-stable

# Verificar versión de Chrome
google-chrome --version

# Instalar librerías de Python
echo "Instalando librerías de Python..."
pip3 install -r requirements.txt

# (Opcional) Instalar timezone data si python < 3.9
echo "Instalando tzdata (opcional)..."
pip3 install tzdata

echo "¡Instalación completada!"
