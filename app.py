from flask import Flask, render_template, request, jsonify, send_file
import yt_dlp
import os
import re
from werkzeug.utils import secure_filename
import logging
from datetime import datetime
import threading
import time
import requests
import glob

# Configuration du logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('app.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.config['SECRET_KEY'] = os.urandom(24)
app.config['UPLOAD_FOLDER'] = 'downloads'

# Créer le dossier de téléchargement s'il n'existe pas
if not os.path.exists(app.config['UPLOAD_FOLDER']):
    os.makedirs(app.config['UPLOAD_FOLDER'])

def extract_video_id(url):
    patterns = [
        r'(?:v=|\/)([0-9A-Za-z_-]{11}).*',
        r'(?:youtu\.be\/)([0-9A-Za-z_-]{11})'
    ]
    
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    return None

def get_file_size_from_url(url):
    """Obtient la taille d'un fichier à partir de son URL en utilisant une requête HEAD"""
    try:
        response = requests.head(url, allow_redirects=True)
        if response.ok:
            size = int(response.headers.get('content-length', 0))
            if size > 0:  # Ne retourner la taille que si elle est valide
                return size
    except Exception as e:
        logger.warning(f"Impossible d'obtenir la taille du fichier: {str(e)}")
    return None  # Retourner None au lieu de 0 pour indiquer une taille invalide

def get_video_info_with_yt_dlp(url):
    """Récupère les informations de la vidéo avec yt-dlp"""
    logger.info(f"Début de l'extraction des informations pour l'URL: {url}")
    
    ydl_opts = {
        'quiet': True,
        'no_warnings': True,
        'extract_flat': False,
        'format': 'best',
    }
    
    try:
        logger.info("Initialisation de yt-dlp")
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            logger.info("Extraction des informations...")
            info = ydl.extract_info(url, download=False)
            logger.info("Informations extraites avec succès")
            formats = info.get('formats', [])
            logger.info(f"Nombre de formats trouvés: {len(formats)}")
            
            video_streams = []
            audio_streams = []
            
            # Récupérer le meilleur stream audio disponible pour la fusion
            best_audio = None
            best_audio_size = None
            for f in formats:
                if f.get('acodec') != 'none' and f.get('vcodec') == 'none':
                    if best_audio is None or (f.get('abr', 0) or 0) > (best_audio.get('abr', 0) or 0):
                        best_audio = f
                        # Obtenir la vraie taille du fichier audio
                        size = get_file_size_from_url(f.get('url', ''))
                        if size is not None:
                            best_audio_size = size
                            logger.info(f"Meilleur format audio trouvé: {f.get('abr', 0)}kbps - Taille réelle: {best_audio_size} bytes")

            logger.info("Traitement des formats...")
            for f in formats:
                try:
                    # Stream vidéo (avec ou sans audio)
                    if f.get('vcodec') != 'none':
                        # Obtenir la vraie taille du fichier vidéo
                        video_url = f.get('url', '')
                        filesize = get_file_size_from_url(video_url)
                        
                        # Si on n'a pas pu obtenir la taille, essayer d'utiliser celle de yt-dlp
                        if filesize is None:
                            filesize = f.get('filesize') or f.get('filesize_approx')
                            if filesize:
                                logger.info(f"Utilisation de la taille yt-dlp: {filesize} bytes")
                        
                        if filesize:  # Ne continuer que si on a une taille valide
                            height = f.get('height', 0) or 0
                            fps = f.get('fps', 0) or 0
                            
                            # Vérifier si c'est un stream adaptatif (vidéo seule)
                            is_adaptive = f.get('acodec') == 'none'
                            
                            # Pour les streams adaptatifs, ajouter la taille de l'audio seulement si nécessaire
                            total_size = filesize
                            if is_adaptive and best_audio_size is not None:
                                total_size += best_audio_size

                            logger.info(f"Format vidéo trouvé: {height}p {fps}fps - Taille vidéo: {filesize} bytes - Total avec audio: {total_size} bytes - Adaptatif: {is_adaptive}")
                            
                            video_streams.append({
                                'itag': f.get('format_id', ''),
                                'resolution': f.get('resolution', 'unknown'),
                                'filesize': total_size,
                                'mime_type': f.get('ext', 'mp4'),
                                'format': f"{height}p - {f.get('ext', 'mp4')}",
                                'url': video_url,
                                'vcodec': f.get('vcodec', ''),
                                'acodec': f.get('acodec', ''),
                                'fps': fps,
                                'height': height,
                                'is_adaptive': is_adaptive,
                                'video_url': video_url,
                                'audio_url': best_audio.get('url') if is_adaptive else None
                            })
                    # Stream audio uniquement
                    elif f.get('acodec') != 'none' and f.get('vcodec') == 'none':
                        audio_url = f.get('url', '')
                        filesize = get_file_size_from_url(audio_url)
                        
                        # Si on n'a pas pu obtenir la taille, essayer d'utiliser celle de yt-dlp
                        if filesize is None:
                            filesize = f.get('filesize') or f.get('filesize_approx')
                            if filesize:
                                logger.info(f"Utilisation de la taille yt-dlp: {filesize} bytes")
                        
                        if filesize:  # Ne continuer que si on a une taille valide
                            abr = f.get('abr', 0) or 0
                            logger.info(f"Format audio trouvé: {abr}kbps - Taille: {filesize} bytes")
                            
                            audio_streams.append({
                                'itag': f.get('format_id', ''),
                                'abr': abr,
                                'filesize': filesize,
                                'format': f"{abr}kbps - {f.get('ext', 'mp4')}",
                                'url': audio_url,
                                'acodec': f.get('acodec', '')
                            })
                except Exception as e:
                    logger.warning(f"Erreur lors du traitement d'un format: {str(e)}")
                    continue
            
            # Trier et filtrer les streams
            def safe_sort_video(x):
                try:
                    return int(x.get('height', 0) or 0)
                except (ValueError, TypeError):
                    return 0
                    
            def safe_sort_audio(x):
                try:
                    return float(x.get('abr', 0) or 0)
                except (ValueError, TypeError):
                    return 0
            
            # Trier et filtrer les streams invalides
            video_streams = [s for s in video_streams if s.get('height', 0) > 0]
            video_streams.sort(key=safe_sort_video, reverse=True)
            
            # Supprimer les doublons de résolution en gardant la meilleure qualité
            seen_resolutions = set()
            unique_video_streams = []
            for stream in video_streams:
                height = stream.get('height', 0)
                if height not in seen_resolutions:
                    seen_resolutions.add(height)
                    unique_video_streams.append(stream)
            
            audio_streams = [s for s in audio_streams if s.get('abr', 0) > 0]
            audio_streams.sort(key=safe_sort_audio, reverse=True)
            
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
        logger.error(f"Erreur yt-dlp: {str(e)}")
        return {'success': False, 'error': str(e)}

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/get-video-info', methods=['POST'])
def get_video_info():
    try:
        logger.info("Réception d'une requête GET-VIDEO-INFO")
        url = request.json['url']
        if not url:
            logger.warning("URL non fournie dans la requête")
            return jsonify({'success': False, 'error': 'URL non fournie'})
        
        logger.info(f"Traitement de l'URL: {url}")
        video_id = extract_video_id(url)
        if not video_id:
            logger.warning(f"Format d'URL YouTube invalide: {url}")
            return jsonify({'success': False, 'error': 'Format d\'URL YouTube invalide'})
        
        logger.info(f"ID vidéo extrait: {video_id}")
        # Utiliser yt-dlp pour récupérer les informations
        result = get_video_info_with_yt_dlp(url)
        logger.info("Résultat obtenu de yt-dlp")
        return jsonify(result)
            
    except Exception as e:
        logger.error(f"Erreur générale dans get-video-info: {str(e)}", exc_info=True)
        return jsonify({
            'success': False,
            'error': f'Erreur inattendue: {str(e)}'
        })

def sanitize_filename(filename):
    """Nettoie le nom de fichier en remplaçant les caractères non autorisés"""
    # Remplacer les caractères non autorisés par des underscores
    invalid_chars = '<>:"/\\|?*'
    for char in invalid_chars:
        filename = filename.replace(char, '_')
    return filename

@app.route('/download', methods=['POST'])
def download():
    try:
        url = request.json['url']
        format_id = request.json['itag']
        download_type = request.json.get('type', 'video')
        is_adaptive = request.json.get('is_adaptive', False)
        quality = request.json.get('quality', '')
        
        # Créer un nom de fichier unique basé sur un timestamp et l'URL
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        video_id = extract_video_id(url) or 'unknown'
        unique_id = f"{timestamp}_{video_id}"
        output_template = os.path.join(app.config['UPLOAD_FOLDER'], f"video_{unique_id}.%(ext)s")
        
        def progress_hook(d):
            if d['status'] == 'downloading':
                downloaded = d.get('downloaded_bytes', 0)
                total = d.get('total_bytes') or d.get('total_bytes_estimate', 0)
                if total > 0:
                    progress = (downloaded / total) * 100
                    logger.info(f"Progression: {progress:.1f}% ({downloaded}/{total} bytes)")
                    # Sauvegarder la progression
                    with open(f'progress_{unique_id}.txt', 'w') as f:
                        f.write(f"{progress}")
            elif d['status'] == 'finished':
                logger.info(f"Téléchargement terminé: {d['filename']}")
                with open(f'progress_{unique_id}.txt', 'w') as f:
                    f.write("100")

        # Créer un fichier de progression vide
        with open(f'progress_{unique_id}.txt', 'w') as f:
            f.write("0")
            
        # Lancer le téléchargement dans un thread séparé
        def download_thread():
            try:
                # Vérifier et supprimer les fichiers existants avec le même nom
                base_filename = f"video_{unique_id}"
                for file in os.listdir(app.config['UPLOAD_FOLDER']):
                    if file.startswith(base_filename):
                        try:
                            file_path = os.path.join(app.config['UPLOAD_FOLDER'], file)
                            os.remove(file_path)
                            logger.info(f"Fichier existant supprimé: {file_path}")
                        except Exception as e:
                            logger.warning(f"Impossible de supprimer {file}: {str(e)}")
                
                # Configurer les options de téléchargement selon le type
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
                    # Pour la vidéo, utiliser le format qui inclut la hauteur demandée
                    # au lieu de se fier à l'id de format qui pourrait causer des problèmes
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
                
                logger.info(f"Téléchargement avec options: {ydl_opts}")
                
                # Exécuter le téléchargement
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    ydl.download([url])
                    
                # À ce stade, progress_hook devrait avoir mis à jour la progression à 100%
                logger.info(f"Téléchargement terminé avec succès")
                
            except Exception as e:
                logger.error(f"Erreur dans le thread de téléchargement: {str(e)}")
                
                # Vérifier si c'est une erreur de fichier existant
                if "Impossible de créer un fichier déjà existant" in str(e):
                    # Essayer de trouver le fichier temporaire et le renommer nous-mêmes
                    try:
                        base_filename = f"video_{unique_id}"
                        temp_file = None
                        target_file = os.path.join(app.config['UPLOAD_FOLDER'], f"{base_filename}.mp4")
                        
                        # Chercher le fichier temporaire
                        for file in os.listdir(app.config['UPLOAD_FOLDER']):
                            if file.startswith(base_filename) and file.endswith('.temp.mp4'):
                                temp_file = os.path.join(app.config['UPLOAD_FOLDER'], file)
                                break
                        
                        # Si le fichier temporaire existe, essayer de le renommer
                        if temp_file and os.path.exists(temp_file):
                            # Si le fichier cible existe déjà, le supprimer d'abord
                            if os.path.exists(target_file):
                                os.remove(target_file)
                                logger.info(f"Fichier existant supprimé: {target_file}")
                            
                            # Renommer le fichier temporaire
                            os.rename(temp_file, target_file)
                            logger.info(f"Fichier renommé manuellement: {temp_file} -> {target_file}")
                            
                            # Mettre la progression à 100%
                            with open(f'progress_{unique_id}.txt', 'w') as f:
                                f.write("100")
                            
                            # Succès !
                            return
                    except Exception as inner_e:
                        logger.error(f"Erreur lors de la récupération du fichier temporaire: {str(inner_e)}")
                
                # En cas d'erreur, mettre la progression à -1 pour indiquer une erreur
                with open(f'progress_{unique_id}.txt', 'w') as f:
                    f.write("-1")
                    
        # Démarrer le thread de téléchargement
        thread = threading.Thread(target=download_thread)
        thread.daemon = True  # Le thread s'arrêtera si le programme principal s'arrête
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
        # Vérifier si le téléchargement est terminé
        progress_file = f'progress_{download_id}.txt'
        if not os.path.exists(progress_file):
            return jsonify({'status': 'error', 'message': 'Téléchargement non trouvé'})
            
        with open(progress_file, 'r') as f:
            progress = float(f.read() or 0)
        
        # Si la progression est négative, c'est une erreur
        if progress < 0:
            return jsonify({
                'status': 'error',
                'message': 'Erreur lors du téléchargement'
            })
        
        # Vérifier si le fichier final existe (après fusion)
        pattern = f"video_{download_id}.*"
        matching_files = []
        for file in os.listdir(app.config['UPLOAD_FOLDER']):
            if re.match(pattern, file) and not any(ext in file for ext in ['.part', '.temp', '.f']):
                matching_files.append(file)
        
        if matching_files:
            filename = matching_files[0]
            file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            
            # Supprimer le fichier de progression
            try:
                os.remove(progress_file)
            except:
                pass
                
            logger.info(f"Fichier trouvé pour {download_id}: {file_path}")
            return jsonify({
                'status': 'complete',
                'filename': filename,
                'filesize': os.path.getsize(file_path),
                'download_id': download_id
            })
            
        # Si la progression est à 100% mais pas de fichier trouvé, attendre encore un peu
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
        logger.info(f"Demande de téléchargement du fichier: {file_path}")
        
        if not os.path.exists(file_path):
            logger.error(f"Fichier non trouvé: {file_path}")
            return jsonify({'success': False, 'error': 'Fichier non trouvé'}), 404
            
        # Déterminer le type MIME
        if filename.endswith('.mp4'):
            mimetype = 'video/mp4'
        elif filename.endswith('.webm'):
            mimetype = 'video/webm'
        elif filename.endswith('.mp3'):
            mimetype = 'audio/mpeg'
        else:
            mimetype = 'application/octet-stream'
            
        logger.info(f"Envoi du fichier: {file_path}, taille: {os.path.getsize(file_path)} bytes, type: {mimetype}")
        
        return send_file(
            file_path,
            mimetype=mimetype,
            as_attachment=True,
            download_name=filename,
            conditional=False
        )
    except Exception as e:
        logger.error(f"Erreur lors du téléchargement du fichier: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/download-file/<download_id>')
def force_download(download_id):
    try:
        # Chercher tous les fichiers correspondant au download_id
        pattern = f"video_{download_id}.*"
        matching_files = []
        
        logger.info(f"Recherche de fichiers correspondant à: {pattern}")
        for file in os.listdir(app.config['UPLOAD_FOLDER']):
            if re.match(pattern, file) and not any(ext in file for ext in ['.part', '.temp', '.f']):
                matching_files.append(file)
                logger.info(f"Fichier trouvé: {file}")
        
        if not matching_files:
            logger.error(f"Aucun fichier trouvé pour le download_id: {download_id}")
            return f"<html><body><h1>Erreur</h1><p>Fichier non trouvé pour {download_id}</p><p><a href='/'>Retour à l'accueil</a></p></body></html>", 404
        
        # Préférer les fichiers MP4
        mp4_files = [f for f in matching_files if f.endswith('.mp4')]
        if mp4_files:
            filename = mp4_files[0]
        else:
            filename = matching_files[0]
        
        file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        logger.info(f"Force download du fichier: {file_path}")
        
        # Déterminer le type MIME
        if filename.endswith('.mp4'):
            mimetype = 'video/mp4'
        elif filename.endswith('.webm'):
            mimetype = 'video/webm'
        elif filename.endswith('.mp3'):
            mimetype = 'audio/mpeg'
        else:
            mimetype = 'application/octet-stream'
        
        # Force le téléchargement en utilisant les bons headers
        resp = send_file(
            file_path,
            mimetype=mimetype,
            as_attachment=True,
            download_name=filename,
            conditional=False
        )
        
        # Ajouter des headers pour éviter les problèmes de cache
        resp.headers['Content-Disposition'] = f'attachment; filename="{filename}"'
        resp.headers['X-Accel-Buffering'] = 'no'
        resp.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
        resp.headers['Pragma'] = 'no-cache'
        resp.headers['Expires'] = '0'
        
        return resp
        
    except Exception as e:
        logger.error(f"Erreur lors du téléchargement forcé: {str(e)}")
        return f"<html><body><h1>Erreur</h1><p>{str(e)}</p><p><a href='/'>Retour à l'accueil</a></p></body></html>", 500

@app.route('/confirm-download/<download_id>', methods=['POST'])
def confirm_download(download_id):
    """
    Endpoint appelé par le client après un téléchargement réussi.
    Va supprimer le fichier du serveur.
    """
    try:
        # Chercher tous les fichiers correspondant au download_id
        pattern = f"video_{download_id}.*"
        files_to_delete = []
        
        logger.info(f"Confirmation de téléchargement reçue pour: {download_id}")
        
        # Trouver tous les fichiers liés à ce téléchargement
        for file in os.listdir(app.config['UPLOAD_FOLDER']):
            if re.match(pattern, file):
                files_to_delete.append(os.path.join(app.config['UPLOAD_FOLDER'], file))
        
        # Supprimer les fichiers après un court délai pour s'assurer que le téléchargement est bien terminé
        def delete_files_after_delay():
            time.sleep(5)  # Attendre 5 secondes pour être sûr
            for file_path in files_to_delete:
                try:
                    if os.path.exists(file_path):
                        os.remove(file_path)
                        logger.info(f"Fichier supprimé après téléchargement: {file_path}")
                except Exception as e:
                    logger.error(f"Erreur lors de la suppression du fichier {file_path}: {str(e)}")
            
            # Supprimer aussi le fichier de progression si existant
            progress_file = f'progress_{download_id}.txt'
            if os.path.exists(progress_file):
                try:
                    os.remove(progress_file)
                    logger.info(f"Fichier de progression supprimé: {progress_file}")
                except Exception as e:
                    logger.error(f"Erreur lors de la suppression du fichier de progression: {str(e)}")
        
        # Lancer la suppression dans un thread séparé
        threading.Thread(target=delete_files_after_delay).start()
        
        return jsonify({'success': True, 'message': 'Fichiers marqués pour suppression'})
    
    except Exception as e:
        logger.error(f"Erreur lors de la confirmation de téléchargement: {str(e)}")
        return jsonify({'success': False, 'error': str(e)})

if __name__ == '__main__':
    app.run(debug=True) 