# app.py

from flask import Flask, render_template, request, redirect, url_for, flash, send_from_directory, session
from functools import wraps
import sqlite3
import pandas as pd
import random
import os
from datetime import datetime

app = Flask(__name__)
app.secret_key = 'gercekten_cok_gizli_bir_anahtar_olmalidir_lutfen_degistir'

DATABASE = 'cekilis_veritabani.db'
UPLOAD_FOLDER = 'uploads'
if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

# --- ADMİN BİLGİLERİ ---
# Gerçek bir uygulamada bunları bir config dosyasından veya ortam değişkeninden okuyun
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
            draw_date TEXT NOT NULL,
            num_winners INTEGER NOT NULl
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

# --- GENEL ROUTE'LAR (PUBLIC) ---
# app.py dosyasının içine, diğer route'ların yanına ekleyin

@app.route('/raffle/participants/<int:raffle_id>')
@login_required
def view_participants(raffle_id):
    conn = get_db_connection()
    raffle = conn.execute('SELECT * FROM raffles WHERE id = ?', (raffle_id,)).fetchone()
    if raffle is None:
        flash('Çekiliş bulunamadı.', 'danger')
        conn.close()
        return redirect(url_for('admin_dashboard'))

    participants = conn.execute(
        'SELECT name FROM participants WHERE raffle_id = ? ORDER BY name', (raffle_id,)
    ).fetchall()
    
    conn.close()
    
    return render_template('admin/participants.html', raffle=raffle, participants=participants)

@app.route('/')
def index():
    conn = get_db_connection()
    raffles = conn.execute('SELECT * FROM raffles ORDER BY draw_date DESC').fetchall()
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
    
    # Oturum durumuna göre hangi layout'u kullanacağına karar ver
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
    
    total_raffles = conn.execute('SELECT COUNT(id) FROM raffles').fetchone()[0]
    total_participants = conn.execute('SELECT COUNT(id) FROM participants').fetchone()[0]
    total_winners = conn.execute('SELECT COUNT(id) FROM winners').fetchone()[0]
    
    raffles_raw = conn.execute('SELECT * FROM raffles ORDER BY draw_date DESC').fetchall()
    
    raffles_list = []
    for raffle in raffles_raw:
        participant_count = conn.execute('SELECT COUNT(id) FROM participants WHERE raffle_id = ?', (raffle['id'],)).fetchone()[0]
        winner_count = conn.execute('SELECT COUNT(id) FROM winners WHERE raffle_id = ?', (raffle['id'],)).fetchone()[0]
        status = "Yapıldı" if winner_count > 0 else "Bekliyor"
        
        # Tarihi daha okunabilir formata çevir
        draw_date_obj = datetime.strptime(raffle['draw_date'], '%Y-%m-%d %H:%M:%S')
        formatted_date = draw_date_obj.strftime('%d.%m.%Y %H:%M')

        raffles_list.append({
            'id': raffle['id'], 'name': raffle['name'], 'draw_date': formatted_date,
            'num_winners': raffle['num_winners'], 'participant_count': participant_count, 'status': status
        })
    
    pending_raffles = sum(1 for r in raffles_list if r['status'] == 'Bekliyor')
    conn.close()
    
    stats = {
        'total_raffles': total_raffles, 'total_participants': total_participants,
        'total_winners': total_winners, 'pending_raffles': pending_raffles
    }
    
    return render_template('admin/dashboard.html', raffles=raffles_list, stats=stats)

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

# --- ÇEKİLİŞ İŞLEM ROUTE'LARI (GİRİŞ KONTROLÜ İLE) ---

@app.route('/upload_participants', methods=['GET', 'POST'])
@login_required
def upload_participants():
    if request.method == 'POST':
        raffle_name = request.form['raffle_name']
        num_winners = request.form['num_winners']
        csv_file = request.files['csv_file']

        if not all([raffle_name, num_winners, csv_file, csv_file.filename]):
            flash('Tüm alanları doldurmak zorunludur.', 'danger')
            return redirect(request.url)

        if not num_winners.isdigit() or int(num_winners) <= 0:
            flash('Kazanacak kişi sayısı pozitif bir sayı olmalıdır.', 'danger')
            return redirect(request.url)

        # GÜNCELLEME: Dosya adını güvenli hale getirin. 
        # Bu, 'ad_soyad,departman,sicil_no.csv' gibi virgül içeren isimlerden kaynaklanabilecek sorunları önler.
        from werkzeug.utils import secure_filename
        filename = secure_filename(csv_file.filename)
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        csv_file.save(filepath)

        try:
            # --- ANA DEĞİŞİKLİK BURADA ---
            # Dosyayı bir 'with' bloğu içinde açıp pandas'a veriyoruz.
            # Bu, bloğun sonunda dosyanın otomatik olarak kapanmasını garanti eder.
            with open(filepath, 'r', encoding='utf-8-sig') as f:
                df = pd.read_csv(f)
            # ---------------------------

            participant_column = 'ad_soyad'
            if participant_column not in df.columns:
                flash(f"CSV dosyasında '{participant_column}' sütunu bulunamadı.", 'danger')
                os.remove(filepath)
                return redirect(request.url)

            participants_from_csv = df[participant_column].dropna().tolist()
            if not participants_from_csv:
                flash('CSV dosyasında geçerli katılımcı bulunamadı.', 'danger')
                os.remove(filepath)
                return redirect(request.url)

            if int(num_winners) > len(participants_from_csv):
                flash(f"Kazanacak kişi sayısı ({len(participants_from_csv)}), katılımcı sayısından ({len(participants_from_csv)}) fazla olamaz!", 'danger')
                os.remove(filepath)
                return redirect(request.url)

            conn = get_db_connection()
            now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            cursor = conn.execute('INSERT INTO raffles (name, draw_date, num_winners) VALUES (?, ?, ?)',
                                  (raffle_name, now, num_winners))
            raffle_id = cursor.lastrowid
            
            participant_data = [(raffle_id, str(name)) for name in participants_from_csv]
            conn.executemany('INSERT INTO participants (raffle_id, name) VALUES (?, ?)', participant_data)
            
            conn.commit()
            conn.close()
            
            # Artık bu satıra gelindiğinde dosya kilidi kalkmış olmalı
            os.remove(filepath)

            flash(f'"{raffle_name}" çekilişi başarıyla oluşturuldu.', 'success')
            return redirect(url_for('admin_dashboard'))

        except Exception as e:
            flash(f'CSV işlenirken bir hata oluştu: {e}', 'danger')
            # Hata durumunda da dosyayı silmeyi dene
            if os.path.exists(filepath):
                try:
                    os.remove(filepath)
                except PermissionError:
                    # Eğer hata durumunda bile kilitliyse, en azından uygulama çökmesin
                    flash("Yüklenen geçici dosya silinemedi, manuel olarak kontrol edebilirsiniz.", "warning")
            return redirect(request.url)
    
    return render_template('admin/upload.html')

@app.route('/draw/<int:raffle_id>')
@login_required
def draw_raffle(raffle_id):
    conn = get_db_connection()
    raffle = conn.execute('SELECT * FROM raffles WHERE id = ?', (raffle_id,)).fetchone()
    
    existing_winners = conn.execute('SELECT * FROM winners WHERE raffle_id = ?', (raffle_id,)).fetchone()
    if existing_winners:
        flash('Bu çekiliş zaten yapılmış.', 'info')
        conn.close()
        return redirect(url_for('view_results', raffle_id=raffle_id))

    participants = conn.execute('SELECT name FROM participants WHERE raffle_id = ?', (raffle_id,)).fetchall()
    participant_names = [p['name'] for p in participants]
    num_winners = raffle['num_winners']

    if len(participant_names) < num_winners:
        flash('Katılımcı sayısı, kazanacak kişi sayısından az. Çekiliş yapılamaz.', 'danger')
        conn.close()
        return redirect(url_for('admin_dashboard'))

    selected_winners = random.sample(participant_names, num_winners)
    winner_data = [(raffle_id, name) for name in selected_winners]
    conn.executemany('INSERT INTO winners (raffle_id, participant_name) VALUES (?, ?)', winner_data)
    
    conn.commit()
    conn.close()

    flash(f'"{raffle["name"]}" çekilişi başarıyla yapıldı!', 'success')
    return redirect(url_for('view_results', raffle_id=raffle_id))


if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)