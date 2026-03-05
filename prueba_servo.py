import serial
import time
import serial.tools.list_ports

# --- CONFIGURACIÓN ---
# ▼▼▼ CAMBIA ESTO al puerto COM donde está conectado tu ESP32 ▼▼▼
SERIAL_PORT = 'COM3'
BAUDRATE = 115200
# ---------------------

def listar_puertos_disponibles():
    """Muestra una lista de los puertos serie disponibles en el sistema."""
    ports = serial.tools.list_ports.comports()
    print("Puertos serie disponibles:")
    if not ports:
        print("  (No se encontraron puertos)")
    for port in ports:
        print(f"  - {port.device}: {port.description}")

def main():
    """Función principal para la herramienta de calibración."""
    print("--- Herramienta de Calibración de Servos para ESP32 ---")
    
    # Intentar conectar al puerto serie
    try:
        ser = serial.Serial(SERIAL_PORT, BAUDRATE, timeout=1)
        time.sleep(2) # Dar tiempo al ESP32 para que se reinicie y esté listo
        print(f"\n✓ Conectado exitosamente a {SERIAL_PORT} a {BAUDRATE} baudios.")
        # Limpiar cualquier dato inicial que el ESP32 envíe al arrancar
        if ser.in_waiting > 0:
            ser.read(ser.in_waiting)
            print("  (Buffer de bienvenida del ESP32 limpiado)")

    except serial.SerialException as e:
        print(f"\n✗ ERROR: No se pudo abrir el puerto '{SERIAL_PORT}'.")
        print(f"   Motivo: {e}")
        listar_puertos_disponibles()
        return

    print("\nIntroduce el comando de tamaño (L, M, S, XS) y presiona Enter.")
    print("Escribe 'salir' para terminar el programa.")
    print("-" * 55)

    while True:
        try:
            # Pedir comando al usuario
            comando = input("Comando > ").strip().upper()

            if comando == 'SALIR':
                print("Cerrando conexión...")
                break

            if comando in ['L', 'M', 'S']:
                # Enviar comando al ESP32 (con el salto de línea)
                ser.write(f"{comando}\n".encode('utf-8'))
                print(f"  → Enviado: '{comando}'")

                # Esperar y leer la respuesta del ESP32
                time.sleep(0.5) # Dar tiempo a que el ESP32 responda
                while ser.in_waiting > 0:
                    respuesta = ser.readline().decode('utf-8').strip()
                    if respuesta:
                        print(f"  ← Respuesta ESP32: {respuesta}")
            else:
                print("  ✗ Comando no válido. Usa solo L, M, S, o XS.")

        except KeyboardInterrupt:
            print("\nInterrupción detectada. Cerrando conexión...")
            break
        except Exception as e:
            print(f"\nHa ocurrido un error: {e}")
            break

    ser.close()
    print("Conexión cerrada. ¡Adiós!")

if __name__ == "__main__":
    main()