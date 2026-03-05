

#mejor sin buenas ni malas
import os
import cv2
import torch
import tkinter as tk
from tkinter import ttk
from PIL import Image, ImageTk, ImageDraw, ImageFont
import numpy as np
import time

from ultralytics import YOLO
import serial
import serial.tools.list_ports
# =================

YOLO_FAMILIAS_PATH = r"C:\Users\Sebastian\OneDrive\Escritorio\Vision\modelo_buenas_malas\best.pt"

# PARÁMETROS
PREFERRED_CAMERA_INDEXES = [0]
CENTER_DETECTION_MARGIN = 50

# CLASIFICACIÓN POR TAMAÑOS
def classify_size_by_area(area):
    """Clasifica el tamaño basado en el área en píxeles²"""
    if area >= 41000:
        return 'L'
    elif area >= 29000:
        return 'M'
    else:
        return 'S'

# CONFIGURACIÓN SERIAL
SERIAL_PORT = 'COM3'
SERIAL_BAUDRATE = 115200

# FUNCIONES SERIAL
def inicializar_serial(port, baudrate):
    """Inicializa la conexión serial con el ESP32"""
    try:
        ser = serial.Serial(port, baudrate, timeout=1)
        time.sleep(2)
        print(f"✓ Conexión serial establecida en {port} a {baudrate} baudios")
        return ser
    except serial.SerialException as e:
        print(f"✗ Error al abrir puerto serial {port}: {e}")
        print("\nPuertos disponibles:")
        ports = serial.tools.list_ports.comports()
        for p in ports:
            print(f"  - {p.device}: {p.description}")
        return None

def enviar_comando_serial(ser, comando):
    """Envía un comando al ESP32 vía serial"""
    if ser is None or not ser.is_open:
        print("✗ Puerto serial no disponible")
        return False

    try:
        mensaje = f"{comando}\n"
        ser.write(mensaje.encode('utf-8'))
        print(f"→ Comando enviado al ESP32: {comando}")

        time.sleep(0.1)
        if ser.in_waiting > 0:
            respuesta = ser.readline().decode('utf-8').strip()
            print(f"← Respuesta ESP32: {respuesta}")

        return True
    except Exception as e:
        print(f"✗ Error al enviar comando: {e}")
        return False

# APP TKINTER
class DetectorApp:
    def __init__(self, root, mode="familias"):
        self.root = root
        self.mode = mode

        self.root.title("Inspección de Piezas - Detección de Familias y Tamaños")
        self.root.geometry("1500x850")
        self.root.configure(bg="#f0f0f0")

        # Estados
        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        self.yolo = None
        self.cap = None
        self.running = False

        self.serial_connection = inicializar_serial(SERIAL_PORT, SERIAL_BAUDRATE)

        # Variables de zona de detección
        self.line1_pos = 400
        self.line2_pos = 880

        # Control de detección
        self.family_detected = False
        self.detected_family = None
        self.piece_in_zone = False
        self.final_area = None
        self.final_size_category = None
        self.locked_box = None
        
        # Guardar última detección completa
        self.last_detected_family = None
        self.last_detected_area = None
        self.last_detected_size_category = None

        # Contadores por tamaño
        self.count_S = 0
        self.count_M = 0
        self.count_L = 0
        
        # Contadores por familia
        self.family_names = []
        self.family_counts = {}

        # UI vars
        self.identificacion_completa_var = tk.StringVar(value="-")
        self.area_actual_var = tk.StringVar(value="Área actual: - px²")
        self.area_final_var = tk.StringVar(value="-")
        self.contador_var = tk.StringVar(value="S: 0 | M: 0 | L: 0")
        self.family_counter_var = tk.StringVar(value="")

        # Estilos
        style = ttk.Style()
        style.theme_use('clam')
        style.configure("TLabel", background="#f0f0f0", foreground="#333", font=('Helvetica', 12))
        style.configure("Header.TLabel", font=('Helvetica', 18, 'bold'))
        style.configure("IDFinal.TLabel", background="#f0f0f0", font=('Consolas', 28, 'bold'), foreground="#cc0000")
        style.configure("Area.TLabel", font=('Consolas', 16, 'bold'), foreground="#0288d1")
        style.configure("Counter.TLabel", font=('Consolas', 14, 'bold'), foreground="#1B5E20")

        self._build_ui()
        self._load_models()
        self._open_camera()
        if self.cap is not None:
            self.running = True
            self._loop()

    def _build_ui(self):
        main_frame = ttk.Frame(self.root, padding=10)
        main_frame.pack(fill=tk.BOTH, expand=True)
        main_frame.grid_columnconfigure(1, weight=1)
        main_frame.grid_rowconfigure(0, weight=1)

        # Columna 0: Controles
        left_panel = ttk.Frame(main_frame, padding=(0, 0, 10, 0))
        left_panel.grid(row=0, column=0, sticky="ns")
        ttk.Label(left_panel, text="Modos", style="Header.TLabel").pack(pady=(0, 10))
        
        self.btn_familias = tk.Button(left_panel, text="🏷 Familias", font=('Helvetica', 13, 'bold'), 
                                       bg="#4CAF50", fg="white", padx=20, pady=10, 
                                       command=lambda: self.switch_mode("familias"))
        self.btn_familias.pack(fill=tk.X, pady=5)
        
        self.btn_tamanos = tk.Button(left_panel, text="📏 Tamaños", font=('Helvetica', 13, 'bold'), 
                                      bg="#2196F3", fg="white", padx=20, pady=10, 
                                      command=lambda: self.switch_mode("tamanos"))
        self.btn_tamanos.pack(fill=tk.X, pady=5)

        self.btn_reset_family_counter = tk.Button(left_panel, text="🔄 Reset Contador Familias", 
                                                   font=('Helvetica', 11, 'bold'), bg="#E91E63", 
                                                   fg="white", padx=15, pady=8, 
                                                   command=self.reset_family_counter)
        self.btn_reset_family_counter.pack(fill=tk.X, pady=(20, 5))

        self.btn_reset_size_counter = tk.Button(left_panel, text="🔄 Reset Contador Tamaños", 
                                                 font=('Helvetica', 11, 'bold'), bg="#FF9800", 
                                                 fg="white", padx=15, pady=8, 
                                                 command=self.reset_size_counter)
        self.btn_reset_size_counter.pack(fill=tk.X, pady=(5, 5))

        # Columna 1: Video e Info
        center_column = ttk.Frame(main_frame)
        center_column.grid(row=0, column=1, sticky="nsew")
        center_column.grid_rowconfigure(1, weight=1)
        center_column.grid_columnconfigure(0, weight=1)

        self.header_label = ttk.Label(center_column, text="", style="Header.TLabel")
        self.header_label.grid(row=0, column=0, pady=(0, 10), sticky="n")

        self.video_label = ttk.Label(center_column, background="black")
        self.video_label.grid(row=1, column=0, sticky="nsew")

        sliders_frame = ttk.Frame(center_column)
        sliders_frame.grid(row=2, column=0, sticky="ew", pady=5)
        ttk.Label(sliders_frame, text="Línea Izquierda:").pack(side=tk.LEFT, padx=5)
        self.slider1 = tk.Scale(sliders_frame, from_=0, to=1280, orient=tk.HORIZONTAL, 
                                command=self._update_line1, length=200)
        self.slider1.set(self.line1_pos)
        self.slider1.pack(side=tk.LEFT, padx=5)
        ttk.Label(sliders_frame, text="Línea Derecha:").pack(side=tk.LEFT, padx=5)
        self.slider2 = tk.Scale(sliders_frame, from_=0, to=1280, orient=tk.HORIZONTAL, 
                                command=self._update_line2, length=200)
        self.slider2.set(self.line2_pos)
        self.slider2.pack(side=tk.LEFT, padx=5)

        self.info_panel = ttk.Frame(center_column)
        self.info_panel.grid(row=3, column=0, sticky="ew", pady=8)

        # Columna 2: Snapshot
        right_panel = ttk.Frame(main_frame, padding=(10, 0, 0, 0))
        right_panel.grid(row=0, column=2, sticky="ns")
        ttk.Label(right_panel, text="Última pieza detectada", font=('Helvetica', 14, 'bold')).pack(pady=(0, 6))
        self.snap_container = ttk.Frame(right_panel, width=320, height=240, relief=tk.SOLID, borderwidth=1)
        self.snap_container.pack()
        self.snap_container.pack_propagate(False)
        self.snapshot_label = ttk.Label(self.snap_container, background="#dddddd")
        self.snapshot_label.pack(expand=True, fill="both")

        self.status = ttk.Label(self.root, text="Cargando…", anchor="w", relief=tk.SUNKEN, padding=5)
        self.status.pack(side=tk.BOTTOM, fill=tk.X)

        self._put_snapshot_placeholder()
        self._render_mode_ui()

    def _render_mode_ui(self):
        for w in self.info_panel.winfo_children():
            w.destroy()
        is_fam_mode = self.mode == "familias"
        self.header_label.config(text="Modo Familias" if is_fam_mode else "Modo Tamaños")
        self.btn_familias.config(relief="sunken" if is_fam_mode else "raised", 
                                 state="disabled" if is_fam_mode else "normal")
        self.btn_tamanos.config(relief="sunken" if not is_fam_mode else "raised", 
                                state="disabled" if not is_fam_mode else "normal")
        
        if is_fam_mode:
            self.btn_reset_family_counter.pack(fill=tk.X, pady=(20, 5))
            self.btn_reset_size_counter.pack_forget()
        else:
            self.btn_reset_family_counter.pack_forget()
            self.btn_reset_size_counter.pack(fill=tk.X, pady=(20, 5))
        
        if is_fam_mode:
            self._build_familias_info(self.info_panel)
        else:
            self._build_tamanos_info(self.info_panel)

    def _build_familias_info(self, parent):
        counter_frame = ttk.Frame(parent, relief=tk.SOLID, borderwidth=2, padding=10)
        counter_frame.pack(pady=5, padx=20, fill=tk.X)
        ttk.Label(counter_frame, text="📊 CONTADOR DE FAMILIAS:", 
                  font=('Helvetica', 12, 'bold')).pack()
        ttk.Label(counter_frame, textvariable=self.family_counter_var, 
                  style="Counter.TLabel", justify=tk.LEFT).pack(pady=2)

        final_frame = ttk.Frame(parent, relief=tk.SOLID, borderwidth=2, padding=10)
        final_frame.pack(pady=10, padx=20, fill=tk.X)
        ttk.Label(final_frame, text="🎯 ÚLTIMA FAMILIA DETECTADA:", 
                  font=('Helvetica', 12, 'bold')).pack()
        ttk.Label(parent, textvariable=self.identificacion_completa_var, 
                  style="IDFinal.TLabel", anchor="center").pack(pady=10)

    def _build_tamanos_info(self, parent):
        rangos_txt = "Rangos (miles de px²): L: 41+ | M: 29-40 | S: 0-28"
        ttk.Label(parent, text=rangos_txt, font=('Consolas', 10), foreground="#555").pack(pady=(0, 10))
        
        counter_frame = ttk.Frame(parent, relief=tk.SOLID, borderwidth=2, padding=10)
        counter_frame.pack(pady=5, padx=20, fill=tk.X)
        ttk.Label(counter_frame, text="📊 CONTADOR DE PIEZAS:", 
                  font=('Helvetica', 12, 'bold')).pack()
        ttk.Label(counter_frame, textvariable=self.contador_var, 
                  style="Counter.TLabel").pack(pady=2)
        
        area_frame = ttk.Frame(parent, relief=tk.SOLID, borderwidth=2, padding=10)
        area_frame.pack(pady=5, padx=20, fill=tk.X)
        ttk.Label(area_frame, text="📐 MEDICIÓN ACTUAL:", 
                  font=('Helvetica', 12, 'bold')).pack()
        ttk.Label(area_frame, textvariable=self.area_actual_var, 
                  style="Area.TLabel").pack(pady=2)
        
        final_frame = ttk.Frame(parent, relief=tk.SOLID, borderwidth=2, padding=10)
        final_frame.pack(pady=10, padx=20, fill=tk.X)
        ttk.Label(final_frame, text="🎯 ÚLTIMO TAMAÑO DETECTADO:", 
                  font=('Helvetica', 12, 'bold')).pack()
        ttk.Label(final_frame, textvariable=self.area_final_var, 
                  style="IDFinal.TLabel").pack()

    def switch_mode(self, new_mode):
        if new_mode == self.mode:
            return
        self.mode = new_mode
        self._reset_current_detection()
        self._render_mode_ui()
        self._restore_last_detection_ui()
        self.status.config(text=f"Modo cambiado a: {self.mode}")

    def reset_size_counter(self):
        """Reinicia el contador de piezas por tamaño"""
        self.count_S = 0
        self.count_M = 0
        self.count_L = 0
        self._update_size_counter_display()
        self.status.config(text="Contador de tamaños reiniciado")

    def _update_size_counter_display(self):
        """Actualiza el texto del contador de tamaños en la UI"""
        self.contador_var.set(f"S: {self.count_S} | M: {self.count_M} | L: {self.count_L}")

    def reset_family_counter(self):
        """Reinicia el contador de piezas por familia"""
        for name in self.family_names:
            self.family_counts[name] = 0
        self._update_family_counter_display()
        self.status.config(text="Contador de familias reiniciado")

    def _update_family_counter_display(self):
        """Actualiza el texto del contador de familias en la UI"""
        if not self.family_counts:
            self.family_counter_var.set("Esperando detección...")
        else:
            counter_text = "\n".join([f"{name.capitalize()}: {count}" 
                                     for name, count in self.family_counts.items()])
            self.family_counter_var.set(counter_text)

    def _reset_current_detection(self, full_reset=True):
        self.family_detected = False
        self.detected_family = None
        self.piece_in_zone = False
        self.final_area = None
        self.final_size_category = None
        self.locked_box = None
        if full_reset:
            self.area_actual_var.set("Área: - px²")
            self.area_final_var.set("-")
            self.identificacion_completa_var.set("-")

    def _restore_last_detection_ui(self):
        if self.last_detected_family:
            family_text = f"{self.last_detected_family.upper()}"
            
            size_text = "-"
            if self.last_detected_area and self.last_detected_size_category:
                size_text = f"{self.last_detected_area:,.0f}px² [{self.last_detected_size_category}]"

            if self.mode == "tamanos":
                self.area_final_var.set(size_text)
                self.identificacion_completa_var.set("-")
            else:
                self.identificacion_completa_var.set(family_text)
                self.area_final_var.set("-")

    def _update_line1(self, val):
        self.line1_pos = int(float(val))

    def _update_line2(self, val):
        self.line2_pos = int(float(val))

    def _put_snapshot_placeholder(self):
        ph = Image.new("RGB", (320, 240), "#cccccc")
        d = ImageDraw.Draw(ph)
        try:
            font = ImageFont.load_default()
        except IOError:
            font = None
        
        d.text((160, 120), "Esperando…", fill="black", anchor="mm", font=font)
        tkimg = ImageTk.PhotoImage(ph)
        self.snapshot_label.imgtk = tkimg
        self.snapshot_label.configure(image=tkimg)

    def _load_models(self):
        try:
            if not os.path.exists(YOLO_FAMILIAS_PATH):
                raise FileNotFoundError(f"No se encontró el modelo YOLO en: {YOLO_FAMILIAS_PATH}")
            
            self.yolo = YOLO(YOLO_FAMILIAS_PATH)
            
            if not self.yolo.names:
                self.yolo.model.fuse()
                print("WARN: Nombres de clases YOLO no cargados, intentando recargar.")
            
            self.family_names = list(self.yolo.names.values())
            self.family_counts = {name: 0 for name in self.family_names}
            self._update_family_counter_display()

            self.status.config(text=f"Modelos cargados: YOLO ({len(self.yolo.names)} clases)")
        
        except Exception as e:
            self.status.config(text=f"Error al cargar modelos: {e}")
            print(f"Error fatal al cargar modelos: {e}")
            self.yolo = None

    def _open_camera(self):
        for idx in PREFERRED_CAMERA_INDEXES:
            self.cap = cv2.VideoCapture(idx, cv2.CAP_DSHOW)
            if self.cap and self.cap.isOpened():
                self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
                self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
                self.status.config(text=f"Cámara abierta (index={idx}).")
                return
        self.status.config(text="No se pudo abrir la cámara.")

    def _loop(self):
        if not self.running or self.cap is None or self.yolo is None:
            self.root.after(100, self._loop)
            return
            
        ok, frame = self.cap.read()
        if not ok:
            self.root.after(100, self._loop)
            return

        h, w, _ = frame.shape
        zone_center_x = (self.line1_pos + self.line2_pos) / 2.0
        cv2.line(frame, (self.line1_pos, 0), (self.line1_pos, h), (0, 255, 255), 2)
        cv2.line(frame, (self.line2_pos, 0), (self.line2_pos, h), (0, 255, 255), 2)

        res = self.yolo(frame, verbose=False)[0]
        best_box = None
        min_dist = float('inf')
        if res.boxes:
            for box in res.boxes:
                x1, y1, x2, y2 = map(int, box.xyxy[0])
                cx = (x1 + x2) / 2
                if self.line1_pos <= cx <= self.line2_pos:
                    dist = abs(cx - zone_center_x)
                    if dist < min_dist:
                        min_dist = dist
                        best_box = box
        
        piece_in_zone = (best_box is not None)
        piece_in_center = piece_in_zone and min_dist <= CENTER_DETECTION_MARGIN

        # Detección en el centro
        if piece_in_center and not self.family_detected:
            self.family_detected = True
            self.piece_in_zone = True
            self.locked_box = tuple(map(int, best_box.xyxy[0]))
            cls_id = int(best_box.cls[0])
            self.detected_family = res.names.get(cls_id, "N/A")
            x1, y1, x2, y2 = self.locked_box
            self.final_area = (x2 - x1) * (y2 - y1)
            self.final_size_category = classify_size_by_area(self.final_area)
            self._update_snapshot(frame[y1:y2, x1:x2])
            print(f"PIEZA DETECTADA: {self.detected_family}, Área: {self.final_area}, Tamaño: {self.final_size_category}")
            if self.mode == "tamanos":
                self.area_actual_var.set(f"{self.final_area:,.0f} px² — [{self.final_size_category}]")

        # Pieza sale de la zona
        if not piece_in_zone and self.piece_in_zone:
            self.last_detected_family = self.detected_family
            self.last_detected_area = self.final_area
            self.last_detected_size_category = self.final_size_category
            
            # ===== ENVÍO DE COMANDOS AL ESP32 =====
            comando_a_enviar = None

            if self.mode == "familias" and self.last_detected_family in self.family_names:
                comando_a_enviar = self.last_detected_family
                self.family_counts[self.last_detected_family] += 1
                self._update_family_counter_display()

            elif self.mode == "tamanos" and self.final_size_category:
                comando_a_enviar = self.final_size_category
                if self.final_size_category == 'S':
                    self.count_S += 1
                elif self.final_size_category == 'M':
                    self.count_M += 1
                elif self.final_size_category == 'L':
                    self.count_L += 1
                self._update_size_counter_display()
            
            if comando_a_enviar:
                enviar_comando_serial(self.serial_connection, comando_a_enviar)
            
            self._restore_last_detection_ui()
            print(f"RESULTADO FINAL: {self.detected_family} | Tamaño: {self.final_size_category}")
            self._reset_current_detection(full_reset=False)

        # Dibujar bounding box
        if self.family_detected and self.locked_box:
            x1, y1, x2, y2 = self.locked_box
            color = (0, 255, 0)  # Verde
            cv2.rectangle(frame, (x1, y1), (x2, y2), color, 3)

        self._show_frame(frame)
        self.root.after(10, self._loop)

    def _show_frame(self, frame_bgr):
        im = Image.fromarray(cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB))
        w, h = self.video_label.winfo_width(), self.video_label.winfo_height()
        if w > 1 and h > 1:
            im.thumbnail((w, h))
        tkimg = ImageTk.PhotoImage(im)
        self.video_label.imgtk = tkimg
        self.video_label.configure(image=tkimg)

    def _update_snapshot(self, bgr):
        if bgr.size == 0:
            return
        im = Image.fromarray(cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB))
        im.thumbnail((320, 240))
        tkimg = ImageTk.PhotoImage(im)
        self.snapshot_label.imgtk = tkimg
        self.snapshot_label.configure(image=tkimg)

    def on_close(self):
        self.running = False
        if self.cap:
            self.cap.release()
        if self.serial_connection:
            self.serial_connection.close()
            print("Conexión serial cerrada.")
        self.root.destroy()

if __name__ == "__main__":
    root = tk.Tk()
    app = DetectorApp(root, "familias")
    root.protocol("WM_DELETE_WINDOW", app.on_close)
    root.mainloop()
