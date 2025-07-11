# app.py (WebSocket entegrasyonundan önceki, client-side animasyonlu tam hali)

from flask import Flask, render_template, request, redirect, url_for, flash, session
from functools import wraps
import sqlite3
import pandas as pd
import random
import os
from datetime import datetime
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.secret_key = 'gercekten_cok_gizli_bir_anahtar_olmalidir_lutfen_degistir'

# --- SABİTLER VE AYARLAR ---
DATABASE = 'cekilis_veritabani.db'
UPLOAD_FOLDER = 'uploads'
if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

ADMIN_USERNAME = 'admin'
ADMIN_PASSWORD = '1234'

# --- VERİTABANI FONKSİYONLARI ---
def get_db_connection():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn

def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS raffles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            creation_date TEXT NOT NULL,
            num_winners INTEGER NOT NULL,
            scheduled_draw_time TEXT NOT NULL
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS participants (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            raffle_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            FOREIGN KEY (raffle_id) REFERENCES raffles (id) ON DELETE CASCADE
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS winners (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            raffle_id INTEGER NOT NULL,
            participant_name TEXT NOT NULL,
            FOREIGN KEY (raffle_id) REFERENCES raffles (id) ON DELETE CASCADE
        )
    ''')
    conn.commit()
    conn.close()

with app.app_context():
    init_db()

# --- ADMİN GİRİŞ KONTROL DECORATOR'I ---
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'logged_in' not in session:
            flash('Bu sayfayı görüntülemek için lütfen giriş yapın.', 'warning')
            return redirect(url_for('admin_login'))
        return f(*args, **kwargs)
    return decorated_function

# --- GENEL (PUBLIC) ROUTE'LAR ---
@app.route('/')
def index():
    conn = get_db_connection()
    raffles = conn.execute('SELECT * FROM raffles ORDER BY creation_date DESC').fetchall()
    conn.close()
    return render_template('index.html', raffles=raffles)

@app.route('/results/<int:raffle_id>')
def view_results(raffle_id):
    conn = get_db_connection()
    raffle = conn.execute('SELECT * FROM raffles WHERE id = ?', (raffle_id,)).fetchone()
    if raffle is None:
        flash('Çekiliş bulunamadı.', 'danger')
        conn.close()
        return redirect(url_for('index'))

    winners = conn.execute('SELECT participant_name FROM winners WHERE raffle_id = ?', (raffle_id,)).fetchall()
    conn.close()
    template_name = 'admin/results.html' if 'logged_in' in session else 'results.html'
    return render_template(template_name, raffle=raffle, winners=winners)

# --- ADMİN PANELİ ROUTE'LARI ---
@app.route('/admin/login', methods=['GET', 'POST'])
def admin_login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        if username == ADMIN_USERNAME and password == ADMIN_PASSWORD:
            session['logged_in'] = True
            flash('Başarıyla giriş yaptınız!', 'success')
            return redirect(url_for('admin_dashboard'))
        else:
            flash('Geçersiz kullanıcı adı veya şifre.', 'danger')
    return render_template('admin/login.html')

@app.route('/admin/logout')
def admin_logout():
    session.pop('logged_in', None)
    flash('Başarıyla çıkış yaptınız.', 'info')
    return redirect(url_for('index'))

@app.route('/admin/dashboard')
@login_required
def admin_dashboard():
    conn = get_db_connection()
    now = datetime.now()
    stats = {
        'total_raffles': conn.execute('SELECT COUNT(id) FROM raffles').fetchone()[0],
        'total_participants': conn.execute('SELECT COUNT(id) FROM participants').fetchone()[0],
        'total_winners': conn.execute('SELECT COUNT(id) FROM winners').fetchone()[0]
    }
    
    raffles_raw = conn.execute('SELECT * FROM raffles ORDER BY scheduled_draw_time DESC').fetchall()
    raffles_list = []
    pending_draw_count = 0
    for raffle in raffles_raw:
        winner_count = conn.execute('SELECT COUNT(id) FROM winners WHERE raffle_id = ?', (raffle['id'],)).fetchone()[0]
        scheduled_time = datetime.strptime(raffle['scheduled_draw_time'], '%Y-%m-%d %H:%M:%S')
        
        status = "Bilinmiyor"
        if winner_count > 0:
            status = "Yapıldı"
        elif scheduled_time > now:
            status = "Zamanlandı"
        else:
            status = "Zamanı Geçti"
            pending_draw_count += 1

        raffles_list.append({
            'id': raffle['id'], 'name': raffle['name'], 'num_winners': raffle['num_winners'],
            'participant_count': conn.execute('SELECT COUNT(id) FROM participants WHERE raffle_id = ?', (raffle['id'],)).fetchone()[0],
            'scheduled_draw_time': scheduled_time.strftime('%d.%m.%Y %H:%M'),
            'status': status
        })
    conn.close()
    stats['pending_raffles'] = pending_draw_count
    return render_template('admin/dashboard.html', raffles=raffles_list, stats=stats)

# --- ÇEKİLİŞ OLUŞTURMA VE YÜKLEME ---
@app.route('/upload_participants', methods=['GET', 'POST'])
@login_required
def upload_participants():
    if request.method == 'POST':
        raffle_name = request.form['raffle_name']
        scheduled_time_str = request.form.get('scheduled_time')
        num_winners = request.form['num_winners']
        csv_file = request.files.get('csv_file')

        if not all([raffle_name, scheduled_time_str, num_winners, csv_file, csv_file.filename]):
            flash('Tüm alanları doldurmak zorunludur.', 'danger')
            return redirect(request.url)

        try:
            scheduled_time = datetime.strptime(scheduled_time_str, '%Y-%m-%dT%H:%M')
            if scheduled_time < datetime.now():
                flash('Çekiliş zamanı geçmiş bir tarih olamaz.', 'danger')
                return redirect(request.url)
        except ValueError:
            flash('Geçersiz tarih/saat formatı.', 'danger')
            return redirect(request.url)

        filename = secure_filename(csv_file.filename)
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        csv_file.save(filepath)

        try:
            df = pd.read_csv(filepath, encoding='utf-8-sig')
            participant_column = 'ad_soyad'
            if participant_column not in df.columns:
                raise ValueError(f"CSV dosyasında '{participant_column}' sütunu bulunamadı.")
            
            participants_from_csv = [str(name) for name in df[participant_column].dropna().tolist()]
            if not participants_from_csv:
                raise ValueError('CSV dosyasında geçerli katılımcı bulunamadı.')
            
            if int(num_winners) > len(participants_from_csv):
                raise ValueError(f"Kazanacak kişi sayısı ({num_winners}), katılımcı sayısından ({len(participants_from_csv)}) fazla olamaz!")

            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute(
                'INSERT INTO raffles (name, creation_date, num_winners, scheduled_draw_time) VALUES (?, ?, ?, ?)',
                (raffle_name, datetime.now().strftime('%Y-%m-%d %H:%M:%S'), num_winners, scheduled_time.strftime('%Y-%m-%d %H:%M:%S'))
            )
            raffle_id = cursor.lastrowid
            
            participant_data = [(raffle_id, name) for name in participants_from_csv]
            conn.executemany('INSERT INTO participants (raffle_id, name) VALUES (?, ?)', participant_data)
            
            conn.commit()
            conn.close()
            
            flash(f'"{raffle_name}" çekilişi başarıyla zamanlandı.', 'success')
            return redirect(url_for('admin_dashboard'))

        except Exception as e:
            flash(f'İşlem sırasında bir hata oluştu: {e}', 'danger')
        
        finally:
            if os.path.exists(filepath):
                os.remove(filepath)
            
    return render_template('admin/upload.html')

# --- KATILIMCI YÖNETİMİ ---
@app.route('/raffle/participants/<int:raffle_id>')
@login_required
def view_participants(raffle_id):
    conn = get_db_connection()
    raffle = conn.execute('SELECT * FROM raffles WHERE id = ?', (raffle_id,)).fetchone()
    if not raffle:
        flash('Çekiliş bulunamadı.', 'danger')
        conn.close()
        return redirect(url_for('admin_dashboard'))

    participants = conn.execute('SELECT id, name FROM participants WHERE raffle_id = ? ORDER BY name', (raffle_id,)).fetchall()
    conn.close()
    return render_template('admin/participants.html', raffle=raffle, participants=participants)

@app.route('/raffle/add_participant/<int:raffle_id>', methods=['POST'])
@login_required
def add_participant(raffle_id):
    name = request.form.get('name')
    if not name or not name.strip():
        flash('Katılımcı adı boş olamaz!', 'danger')
        return redirect(url_for('view_participants', raffle_id=raffle_id))

    conn = get_db_connection()
    conn.execute('INSERT INTO participants (raffle_id, name) VALUES (?, ?)', (raffle_id, name.strip()))
    conn.commit()
    conn.close()
    flash(f'"{name.strip()}" başarıyla eklendi.', 'success')
    return redirect(url_for('view_participants', raffle_id=raffle_id))

@app.route('/participant/delete/<int:participant_id>', methods=['POST'])
@login_required
def delete_participant(participant_id):
    conn = get_db_connection()
    raffle_id = conn.execute('SELECT raffle_id FROM participants WHERE id = ?', (participant_id,)).fetchone()['raffle_id']
    conn.execute('DELETE FROM participants WHERE id = ?', (participant_id,))
    conn.commit()
    conn.close()
    flash('Katılımcı başarıyla silindi.', 'success')
    return redirect(url_for('view_participants', raffle_id=raffle_id))

@app.route('/participant/edit/<int:participant_id>', methods=['GET', 'POST'])
@login_required
def edit_participant(participant_id):
    conn = get_db_connection()
    participant = conn.execute('SELECT * FROM participants WHERE id = ?', (participant_id,)).fetchone()

    if request.method == 'POST':
        new_name = request.form['name']
        if not new_name:
            flash('Katılımcı adı boş olamaz.', 'danger')
        else:
            conn.execute('UPDATE participants SET name = ? WHERE id = ?', (new_name, participant_id))
            conn.commit()
            flash('Katılımcı adı başarıyla güncellendi.', 'success')
            return redirect(url_for('view_participants', raffle_id=participant['raffle_id']))
    conn.close()
    return render_template('admin/edit_participant.html', participant=participant)

# --- ÇEKİLİŞ YÖNETİMİ ---
@app.route('/raffle/delete/<int:raffle_id>', methods=['POST'])
@login_required
def delete_raffle(raffle_id):
    conn = get_db_connection()
    raffle = conn.execute('SELECT name FROM raffles WHERE id = ?', (raffle_id,)).fetchone()
    if raffle:
        conn.execute('DELETE FROM raffles WHERE id = ?', (raffle_id,))
        conn.commit()
        flash(f'"{raffle["name"]}" adlı çekiliş ve tüm verileri kalıcı olarak silindi.', 'success')
    else:
        flash('Silinmek istenen çekiliş bulunamadı.', 'danger')
    conn.close()
    return redirect(url_for('admin_dashboard'))

@app.route('/raffle/reset/<int:raffle_id>', methods=['POST'])
@login_required
def reset_raffle(raffle_id):
    conn = get_db_connection()
    conn.execute('DELETE FROM winners WHERE raffle_id = ?', (raffle_id,))
    conn.commit()
    conn.close()
    flash('Çekiliş sıfırlandı. Şimdi yeniden çekebilirsiniz.', 'success')
    return redirect(url_for('admin_dashboard'))

# --- ÇEKİLİŞİ YAPMA VE ANİMASYON (CLIENT-SIDE) ---
@app.route('/draw/<int:raffle_id>')
@login_required
def draw_raffle(raffle_id):
    force_draw = request.args.get('force', 'false').lower() == 'true'

    conn = get_db_connection()
    raffle = conn.execute('SELECT * FROM raffles WHERE id = ?', (raffle_id,)).fetchone()
    
    if not raffle:
        flash("Çekiliş bulunamadı!", "danger")
        conn.close()
        return redirect(url_for('admin_dashboard'))

    scheduled_time = datetime.strptime(raffle['scheduled_draw_time'], '%Y-%m-%d %H:%M:%S')
    if not force_draw and scheduled_time > datetime.now():
        flash("Bu çekilişin zamanı henüz gelmedi!", "warning")
        conn.close()
        return redirect(url_for('admin_dashboard'))

    existing_winners = conn.execute('SELECT participant_name FROM winners WHERE raffle_id = ?', (raffle_id,)).fetchall()
    if existing_winners:
        flash('Bu çekiliş zaten yapılmış. Sonuçları sıfırlayarak tekrar çekebilirsiniz.', 'info')
        conn.close()
        return redirect(url_for('view_results', raffle_id=raffle_id))

    participants = conn.execute('SELECT name FROM participants WHERE raffle_id = ?', (raffle_id,)).fetchall()
    participant_names = [p['name'] for p in participants]
    num_winners = raffle['num_winners']

    if len(participant_names) < num_winners:
        flash('Katılımcı sayısı, kazanacak kişi sayısından az. Çekiliş yapılamaz.', 'danger')
        conn.close()
        return redirect(url_for('admin_dashboard'))

    # Kazananları belirle ve veritabanına kaydet
    selected_winners = random.sample(participant_names, num_winners)
    winner_data = [(raffle_id, name) for name in selected_winners]
    conn.executemany('INSERT INTO winners (raffle_id, participant_name) VALUES (?, ?)', winner_data)
    
    conn.commit()
    conn.close()

    # Kazananları ve tüm katılımcıları animasyon sayfasına gönder
    return render_template(
        'admin/drawing_animation.html', 
        raffle=raffle, 
        winners=selected_winners, 
        all_participants=participant_names
    )

# --- UYGULAMAYI BAŞLATMA ---
if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
