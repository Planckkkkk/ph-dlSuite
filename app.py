from flask import Flask, render_template, request, jsonify, send_file
import yt_dlp
import os
import re
from datetime import datetime
import threading
import time
import logging

# Configuration du logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.config['SECRET_KEY'] = os.urandom(24)
app.config['UPLOAD_FOLDER'] = 'downloads'

# Créer le dossier de téléchargement s'il n'existe pas
if not os.path.exists(app.config['UPLOAD_FOLDER']):
    os.makedirs(app.config['UPLOAD_FOLDER'])


def extract_video_id(url):
    """Extrait l'ID vidéo YouTube d'une URL"""
    patterns = [
        r'(?:v=|\/)([0-9A-Za-z_-]{11}).*',
        r'(?:youtu\.be\/)([0-9A-Za-z_-]{11})'
    ]

    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    return None


def get_video_info(url):
    """Récupère les informations de la vidéo avec yt-dlp"""
    logger.info(f"Extraction des informations pour: {url}")

    ydl_opts = {
        'quiet': True,
        'no_warnings': True,
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)

            # Préparer les streams vidéo et audio
            video_streams = []
            audio_streams = []

            # Trouver le meilleur audio pour les streams adaptatifs
            best_audio = None
            for f in info.get('formats', []):
                if f.get('acodec') != 'none' and f.get('vcodec') == 'none':
                    if best_audio is None or (f.get('abr', 0) or 0) > (best_audio.get('abr', 0) or 0):
                        best_audio = f

            # Traiter tous les formats
            for f in info.get('formats', []):
                # Stream vidéo
                if f.get('vcodec') != 'none':
                    height = f.get('height', 0) or 0
                    fps = f.get('fps', 0) or 0
                    filesize = f.get('filesize') or f.get('filesize_approx', 0) or 0

                    # Vérifier si c'est un stream adaptatif (vidéo seule)
                    is_adaptive = f.get('acodec') == 'none'

                    # Pour les streams adaptatifs, estimer la taille totale
                    total_size = filesize
                    if is_adaptive and best_audio:
                        best_audio_size = best_audio.get('filesize') or best_audio.get('filesize_approx', 0) or 0
                        total_size += best_audio_size

                    if height > 0:  # Ignorer les formats sans hauteur valide
                        video_streams.append({
                            'itag': f.get('format_id', ''),
                            'resolution': f.get('resolution', f"{height}p"),
                            'filesize': total_size,
                            'mime_type': f.get('ext', 'mp4'),
                            'format': f"{height}p - {f.get('ext', 'mp4')}",
                            'url': f.get('url', ''),
                            'vcodec': f.get('vcodec', ''),
                            'acodec': f.get('acodec', ''),
                            'fps': fps,
                            'height': height,
                            'is_adaptive': is_adaptive,
                            'video_url': f.get('url', ''),
                            'audio_url': best_audio.get('url') if is_adaptive else None
                        })

                # Stream audio
                elif f.get('acodec') != 'none' and f.get('vcodec') == 'none':
                    abr = f.get('abr', 0) or 0
                    filesize = f.get('filesize') or f.get('filesize_approx', 0) or 0

                    if abr > 0:  # Ignorer les formats sans bitrate valide
                        audio_streams.append({
                            'itag': f.get('format_id', ''),
                            'abr': abr,
                            'filesize': filesize,
                            'format': f"{abr}kbps - {f.get('ext', 'mp3')}",
                            'url': f.get('url', ''),
                            'acodec': f.get('acodec', '')
                        })

            # Trier les streams par qualité (hauteur pour vidéo, bitrate pour audio)
            video_streams.sort(key=lambda x: x.get('height', 0), reverse=True)
            audio_streams.sort(key=lambda x: x.get('abr', 0), reverse=True)

            # Supprimer les doublons de résolution
            seen_resolutions = set()
            unique_video_streams = []
            for stream in video_streams:
                height = stream.get('height', 0)
                if height not in seen_resolutions:
                    seen_resolutions.add(height)
                    unique_video_streams.append(stream)

            return {
                'success': True,
                'data': {
                    'title': info.get('title', ''),
                    'thumbnail': info.get('thumbnail', ''),
                    'duration': info.get('duration', 0) or 0,
                    'author': info.get('uploader', 'Unknown'),
                    'url': url,
                    'video_id': info.get('id', ''),
                    'streams': {
                        'video': unique_video_streams,
                        'audio': audio_streams
                    }
                }
            }
    except Exception as e:
        logger.error(f"Erreur lors de l'extraction des informations: {str(e)}")
        return {'success': False, 'error': str(e)}


@app.route('/')
def index():
    return render_template('index.html')


@app.route('/get-video-info', methods=['POST'])
def get_video_info_route():
    try:
        url = request.json['url']
        if not url:
            return jsonify({'success': False, 'error': 'URL non fournie'})

        video_id = extract_video_id(url)
        if not video_id:
            return jsonify({'success': False, 'error': 'Format d\'URL YouTube invalide'})

        result = get_video_info(url)
        return jsonify(result)

    except Exception as e:
        logger.error(f"Erreur dans get-video-info: {str(e)}")
        return jsonify({
            'success': False,
            'error': f'Erreur inattendue: {str(e)}'
        })


@app.route('/download', methods=['POST'])
def download():
    try:
        url = request.json['url']
        format_id = request.json['itag']
        download_type = request.json.get('type', 'video')
        is_adaptive = request.json.get('is_adaptive', False)
        quality = request.json.get('quality', '')

        # Créer un nom de fichier unique
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        video_id = extract_video_id(url) or 'unknown'
        unique_id = f"{timestamp}_{video_id}"
        output_template = os.path.join(app.config['UPLOAD_FOLDER'], f"video_{unique_id}.%(ext)s")

        # Créer un fichier de progression
        progress_file = f'progress_{unique_id}.txt'
        with open(progress_file, 'w') as f:
            f.write("0")

        def progress_hook(d):
            if d['status'] == 'downloading':
                downloaded = d.get('downloaded_bytes', 0)
                total = d.get('total_bytes') or d.get('total_bytes_estimate', 0)
                if total > 0:
                    progress = (downloaded / total) * 100
                    with open(progress_file, 'w') as f:
                        f.write(f"{progress}")
            elif d['status'] == 'finished':
                with open(progress_file, 'w') as f:
                    f.write("100")

        def download_thread():
            try:
                # Configurer les options de téléchargement
                if download_type == 'audio':
                    ydl_opts = {
                        'format': 'bestaudio',
                        'outtmpl': output_template,
                        'progress_hooks': [progress_hook],
                        'postprocessors': [{
                            'key': 'FFmpegExtractAudio',
                            'preferredcodec': 'mp3',
                            'preferredquality': '192',
                        }]
                    }
                else:
                    # Pour la vidéo, utiliser le format spécifié par la hauteur
                    if is_adaptive:
                        format_spec = f"bestvideo[height<={quality}]+bestaudio/best"
                    else:
                        format_spec = f"best[height<={quality}]/best"

                    ydl_opts = {
                        'format': format_spec,
                        'outtmpl': output_template,
                        'progress_hooks': [progress_hook],
                        'merge_output_format': 'mp4'
                    }

                # Exécuter le téléchargement
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    ydl.download([url])

            except Exception as e:
                logger.error(f"Erreur dans le téléchargement: {str(e)}")
                with open(progress_file, 'w') as f:
                    f.write("-1")

        # Démarrer le téléchargement dans un thread séparé
        thread = threading.Thread(target=download_thread)
        thread.daemon = True
        thread.start()

        return jsonify({
            'success': True,
            'timestamp': unique_id,
            'message': 'Téléchargement démarré',
            'video_id': video_id
        })

    except Exception as e:
        logger.error(f"Erreur de téléchargement: {str(e)}")
        return jsonify({'success': False, 'error': str(e)})


@app.route('/download-progress/<timestamp>')
def download_progress(timestamp):
    try:
        progress_file = f'progress_{timestamp}.txt'
        if os.path.exists(progress_file):
            with open(progress_file, 'r') as f:
                progress = float(f.read() or 0)
            return jsonify({'progress': progress})
        return jsonify({'progress': 0})
    except Exception as e:
        logger.error(f"Erreur lors de la lecture de la progression: {str(e)}")
        return jsonify({'progress': 0})


@app.route('/download-status/<download_id>')
def download_status(download_id):
    try:
        # Vérifier le fichier de progression
        progress_file = f'progress_{download_id}.txt'
        if not os.path.exists(progress_file):
            return jsonify({'status': 'error', 'message': 'Téléchargement non trouvé'})

        with open(progress_file, 'r') as f:
            progress = float(f.read() or 0)

        # Vérifier s'il y a une erreur
        if progress < 0:
            return jsonify({'status': 'error', 'message': 'Erreur lors du téléchargement'})

        # Vérifier si le fichier final existe
        pattern = f"video_{download_id}.*"
        matching_files = []
        for file in os.listdir(app.config['UPLOAD_FOLDER']):
            if re.match(pattern, file) and not any(ext in file for ext in ['.part', '.temp', '.f']):
                matching_files.append(file)

        if matching_files:
            filename = matching_files[0]
            file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)

            return jsonify({
                'status': 'complete',
                'filename': filename,
                'filesize': os.path.getsize(file_path),
                'download_id': download_id
            })

        # Si la progression est à 100% mais pas de fichier trouvé, attendre encore
        if progress >= 100:
            return jsonify({'status': 'downloading', 'progress': 99})

        # Retourner la progression actuelle
        return jsonify({'status': 'downloading', 'progress': progress})

    except Exception as e:
        logger.error(f"Erreur lors de la vérification du statut: {str(e)}")
        return jsonify({'status': 'error', 'message': str(e)})


@app.route('/downloads/<path:filename>')
def download_file(filename):
    try:
        file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)

        if not os.path.exists(file_path):
            return jsonify({'success': False, 'error': 'Fichier non trouvé'}), 404

        # Déterminer le type MIME
        mimetype = 'application/octet-stream'
        if filename.endswith('.mp4'):
            mimetype = 'video/mp4'
        elif filename.endswith('.webm'):
            mimetype = 'video/webm'
        elif filename.endswith('.mp3'):
            mimetype = 'audio/mpeg'

        return send_file(
            file_path,
            mimetype=mimetype,
            as_attachment=True,
            download_name=filename
        )
    except Exception as e:
        logger.error(f"Erreur lors du téléchargement du fichier: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/download-file/<download_id>')
def force_download(download_id):
    try:
        # Chercher le fichier correspondant
        pattern = f"video_{download_id}.*"
        matching_files = []

        for file in os.listdir(app.config['UPLOAD_FOLDER']):
            if re.match(pattern, file) and not any(ext in file for ext in ['.part', '.temp', '.f']):
                matching_files.append(file)

        if not matching_files:
            return f"<html><body><h1>Erreur</h1><p>Fichier non trouvé</p><p><a href='/'>Retour à l'accueil</a></p></body></html>", 404

        # Préférer les fichiers MP4
        mp4_files = [f for f in matching_files if f.endswith('.mp4')]
        filename = mp4_files[0] if mp4_files else matching_files[0]

        file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)

        # Déterminer le type MIME
        mimetype = 'application/octet-stream'
        if filename.endswith('.mp4'):
            mimetype = 'video/mp4'
        elif filename.endswith('.webm'):
            mimetype = 'video/webm'
        elif filename.endswith('.mp3'):
            mimetype = 'audio/mpeg'

        # Force le téléchargement
        resp = send_file(
            file_path,
            mimetype=mimetype,
            as_attachment=True,
            download_name=filename
        )

        # Ajouter des headers pour éviter les problèmes de cache
        resp.headers['Content-Disposition'] = f'attachment; filename="{filename}"'
        resp.headers['Cache-Control'] = 'no-cache'

        return resp

    except Exception as e:
        logger.error(f"Erreur lors du téléchargement forcé: {str(e)}")
        return f"<html><body><h1>Erreur</h1><p>{str(e)}</p><p><a href='/'>Retour à l'accueil</a></p></body></html>", 500


@app.route('/confirm-download/<download_id>', methods=['POST'])
def confirm_download(download_id):
    """Supprimer le fichier du serveur après téléchargement"""
    try:
        # Chercher les fichiers correspondants
        pattern = f"video_{download_id}.*"
        files_to_delete = []

        for file in os.listdir(app.config['UPLOAD_FOLDER']):
            if re.match(pattern, file):
                files_to_delete.append(os.path.join(app.config['UPLOAD_FOLDER'], file))

        # Supprimer les fichiers après un court délai
        def delete_files_after_delay():
            time.sleep(5)  # Attendre 5 secondes
            for file_path in files_to_delete:
                try:
                    if os.path.exists(file_path):
                        os.remove(file_path)
                        logger.info(f"Fichier supprimé: {file_path}")
                except Exception as e:
                    logger.error(f"Erreur lors de la suppression: {str(e)}")

            # Supprimer le fichier de progression
            progress_file = f'progress_{download_id}.txt'
            if os.path.exists(progress_file):
                try:
                    os.remove(progress_file)
                except Exception:
                    pass

        # Lancer la suppression dans un thread séparé
        threading.Thread(target=delete_files_after_delay).start()

        return jsonify({'success': True, 'message': 'Fichiers marqués pour suppression'})

    except Exception as e:
        logger.error(f"Erreur lors de la confirmation: {str(e)}")
        return jsonify({'success': False, 'error': str(e)})


if __name__ == '__main__':
    app.run(debug=True)