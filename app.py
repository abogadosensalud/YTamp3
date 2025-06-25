from flask import Flask, request, jsonify, send_file
from flask_cors import CORS
import yt_dlp
import os
import tempfile
import uuid
from datetime import datetime, timedelta
import threading
import time

app = Flask(__name__)
CORS(app)  # Permitir requests desde el frontend

# Configuración
DOWNLOAD_DIR = tempfile.gettempdir()
MAX_FILE_AGE = 3600  # 1 hora en segundos

def cleanup_old_files():
    """Limpia archivos antiguos cada hora"""
    while True:
        try:
            now = time.time()
            for filename in os.listdir(DOWNLOAD_DIR):
                if filename.startswith('yt_download_'):
                    filepath = os.path.join(DOWNLOAD_DIR, filename)
                    if os.path.isfile(filepath):
                        file_age = now - os.path.getmtime(filepath)
                        if file_age > MAX_FILE_AGE:
                            os.remove(filepath)
                            print(f"Archivo eliminado: {filename}")
        except Exception as e:
            print(f"Error en limpieza: {e}")
        
        time.sleep(3600)  # Esperar 1 hora

# Iniciar hilo de limpieza
cleanup_thread = threading.Thread(target=cleanup_old_files, daemon=True)
cleanup_thread.start()

def get_video_info(url):
    """Obtiene información del video sin descargarlo"""
    ydl_opts = {
        'quiet': True,
        'no_warnings': True,
    }
    
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=False)
        return {
            'title': info.get('title', 'Sin título'),
            'duration': format_duration(info.get('duration', 0)),
            'uploader': info.get('uploader', 'Desconocido'),
            'view_count': info.get('view_count', 0)
        }

def format_duration(seconds):
    """Formatea duración en formato legible"""
    if not seconds:
        return "Desconocida"
    
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    seconds = seconds % 60
    
    if hours > 0:
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
    else:
        return f"{minutes:02d}:{seconds:02d}"

def download_content(url, format_type):
    """Descarga contenido de YouTube"""
    
    # ID único para el archivo
    unique_id = str(uuid.uuid4())[:8]
    
    # Configurar opciones según el formato
    if format_type == 'mp3':
        ydl_opts = {
            'format': 'bestaudio/best',
            'outtmpl': os.path.join(DOWNLOAD_DIR, f'yt_download_{unique_id}.%(ext)s'),
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192',
            }],
            'quiet': True,
            'no_warnings': True,
        }
    elif format_type == 'mp4':
        ydl_opts = {
            'format': 'best[ext=mp4]/best',
            'outtmpl': os.path.join(DOWNLOAD_DIR, f'yt_download_{unique_id}.%(ext)s'),
            'quiet': True,
            'no_warnings': True,
        }
    else:  # webm
        ydl_opts = {
            'format': 'best',
            'outtmpl': os.path.join(DOWNLOAD_DIR, f'yt_download_{unique_id}.%(ext)s'),
            'quiet': True,
            'no_warnings': True,
        }
    
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            # Obtener info del video
            info = ydl.extract_info(url, download=False)
            
            # Descargar
            ydl.download([url])
            
            # Encontrar el archivo descargado
            downloaded_file = None
            for filename in os.listdir(DOWNLOAD_DIR):
                if filename.startswith(f'yt_download_{unique_id}'):
                    downloaded_file = os.path.join(DOWNLOAD_DIR, filename)
                    break
            
            if not downloaded_file or not os.path.exists(downloaded_file):
                raise Exception("No se pudo encontrar el archivo descargado")
            
            return {
                'filepath': downloaded_file,
                'filename': os.path.basename(downloaded_file),
                'title': info.get('title', 'Sin título'),
                'duration': format_duration(info.get('duration', 0))
            }
            
    except Exception as e:
        raise Exception(f"Error en descarga: {str(e)}")

@app.route('/')
def home():
    return jsonify({
        'message': 'YouTube Downloader API funcionando',
        'version': '1.0',
        'endpoints': {
            '/info': 'GET - Obtener información de video',
            '/download': 'POST - Descargar contenido'
        }
    })

@app.route('/info')
def video_info():
    """Obtiene información de un video"""
    url = request.args.get('url')
    
    if not url:
        return jsonify({'error': 'URL requerida'}), 400
    
    try:
        info = get_video_info(url)
        return jsonify(info)
    except Exception as e:
        return jsonify({'error': str(e)}), 400

@app.route('/download', methods=['POST'])
def download():
    """Procesa descarga de contenido"""
    data = request.get_json()
    
    if not data or 'url' not in data:
        return jsonify({'error': 'URL requerida'}), 400
    
    url = data['url']
    format_type = data.get('format', 'mp3')
    
    # Validar formato
    if format_type not in ['mp3', 'mp4', 'webm']:
        return jsonify({'error': 'Formato no válido'}), 400
    
    try:
        result = download_content(url, format_type)
        
        # Crear URL de descarga
        download_url = f"/file/{os.path.basename(result['filepath'])}"
        
        return jsonify({
            'success': True,
            'title': result['title'],
            'duration': result['duration'],
            'format': format_type,
            'download_url': download_url,
            'filename': result['filename']
        })
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/file/<filename>')
def download_file(filename):
    """Sirve archivos descargados"""
    filepath = os.path.join(DOWNLOAD_DIR, filename)
    
    if not os.path.exists(filepath):
        return jsonify({'error': 'Archivo no encontrado'}), 404
    
    # Verificar que el archivo es de nuestro sistema
    if not filename.startswith('yt_download_'):
        return jsonify({'error': 'Acceso denegado'}), 403
    
    return send_file(filepath, as_attachment=True)

@app.route('/health')
def health_check():
    """Endpoint de salud para monitoring"""
    return jsonify({
        'status': 'healthy',
        'timestamp': datetime.now().isoformat(),
        'temp_dir': DOWNLOAD_DIR
    })

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    debug = os.environ.get('DEBUG', 'False').lower() == 'true'
    
    app.run(host='0.0.0.0', port=port, debug=debug)
