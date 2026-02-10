
#!/bin/bash

# Detectar si estamos en Amazon Linux / RHEL (yum) o Debian/Ubuntu (apt)
if command -v yum &> /dev/null; then
    echo "Detectado sistema basado en 'yum' (Amazon Linux / RHEL / CentOS)."
    
    # 1. Actualizar sistema
    echo "Actualizando sistema..."
    sudo yum update -y

    # 2. Instalar dependencias básicas
    echo "Instalando utilidades básica..."
    sudo yum install -y python3-pip wget unzip

    # 3. Instalar Google Chrome (RPM)
    echo "Descargando e inatalando Google Chrome..."
    wget https://dl.google.com/linux/direct/google-chrome-stable_current_x86_64.rpm
    sudo yum install -y ./google-chrome-stable_current_x86_64.rpm
    rm google-chrome-stable_current_x86_64.rpm

elif command -v apt-get &> /dev/null; then
    echo "Detectado sistema basado en 'apt' (Ubuntu / Debian)."

    # 1. Actualizar sistema
    sudo apt-get update && sudo apt-get upgrade -y
    
    # 2. Instalar dependencias
    sudo apt-get install -y python3 python3-pip python3-venv unzip curl wget

    # 3. Instalar Chrome
    echo "Instalando Google Chrome..."
    wget -q -O - https://dl-ssl.google.com/linux/linux_signing_key.pub | sudo apt-key add -
    sudo sh -c 'echo "deb [arch=amd64] http://dl.google.com/linux/chrome/deb/ stable main" >> /etc/apt/sources.list.d/google-chrome.list'
    sudo apt-get update
    sudo apt-get install -y google-chrome-stable

else
    echo "Error: No se detectó ni 'yum' ni 'apt-get'. Sistema no soportado automáticamente."
    exit 1
fi

# 4. Verificar Chrome
if command -v google-chrome &> /dev/null; then
    echo "Google Chrome instalado correctamente:"
    google-chrome --version
else
    echo "ADVERTENCIA: No se pudo verificar la instalación de Google Chrome."
fi

# 5. Instalar librerías Python
echo "Instalando librerías de Python desde requirements.txt..."
# En Amazon Linux 2023, a veces pip3 pide usar un venv, o usar --user, o sudo.
# Intentaremos instalación global con sudo para simplificar el setup en EC2.
sudo pip3 install -r requirements.txt

echo "¡Instalación completada!"
