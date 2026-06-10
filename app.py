from flask import Flask, render_template, request, jsonify, send_from_directory, session
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
import json, os, copy, base64, zlib, hashlib, secrets

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

app = Flask(__name__,
            template_folder=os.path.join(BASE_DIR, 'templates'),
            static_folder=os.path.join(BASE_DIR, 'static'))
app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{BASE_DIR}/data/langlearn.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SECRET_KEY'] = 'langlearn-secret-2024'

# O'qituvchi paroli — SHA-256 hash of '200519992806'
TEACHER_PASS_HASH = hashlib.sha256(b'200519992806').hexdigest()

# .urok fayl magic bytes
UROK_MAGIC   = b'UROKFILE'
UROK_VERSION = 2

# ─── Shifrlash yordamchilari ──────────────────────────────────────────────────

def _xor_bytes(data: bytes, key: bytes) -> bytes:
    return bytes(b ^ key[i % len(key)] for i, b in enumerate(data))

def encode_urok(payload: dict) -> str:
    """dict → shifrlangan base64 string (.urok fayl ichiga yoziladi)"""
    raw        = json.dumps(payload, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
    compressed = zlib.compress(raw, level=9)
    key        = b'LangLearn2024xK9'
    xored      = _xor_bytes(compressed, key)
    final      = UROK_MAGIC + bytes([UROK_VERSION]) + xored
    return base64.b64encode(final).decode('ascii')

def decode_urok(b64_str: str) -> dict:
    """shifrlangan base64 string → dict"""
    try:
        raw = base64.b64decode(b64_str.strip())
    except Exception:
        raise ValueError("Base64 decode xatosi")
    if not raw.startswith(UROK_MAGIC):
        raise ValueError("Noto'g'ri fayl formati (magic bytes mos emas)")
    # version = raw[len(UROK_MAGIC)]  # kelajakda versiya farqlash uchun
    data       = raw[len(UROK_MAGIC) + 1:]
    key        = b'LangLearn2024xK9'
    compressed = _xor_bytes(data, key)
    jsonbytes  = zlib.decompress(compressed)
    return json.loads(jsonbytes.decode('utf-8'))

# ─── Models ───────────────────────────────────────────────────────────────────

db = SQLAlchemy(app)

class Lesson(db.Model):
    id         = db.Column(db.Integer, primary_key=True)
    title      = db.Column(db.String(200), nullable=False)
    subtitle   = db.Column(db.String(200), default='')
    order      = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    blocks     = db.relationship('Block', backref='lesson', lazy=True,
                                 cascade='all, delete-orphan',
                                 order_by='Block.order')

class Block(db.Model):
    id         = db.Column(db.Integer, primary_key=True)
    lesson_id  = db.Column(db.Integer, db.ForeignKey('lesson.id'), nullable=False)
    type       = db.Column(db.String(50), nullable=False)
    order      = db.Column(db.Integer, default=0)
    data       = db.Column(db.Text, default='{}')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            'id': self.id,
            'lesson_id': self.lesson_id,
            'type': self.type,
            'order': self.order,
            'data': json.loads(self.data or '{}'),
        }

class StudentProgress(db.Model):
    id         = db.Column(db.Integer, primary_key=True)
    block_id   = db.Column(db.Integer, db.ForeignKey('block.id'), nullable=False)
    answers    = db.Column(db.Text, default='{}')
    score      = db.Column(db.Float, default=0)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

# .urok natijalar jadvali
class StudentResult(db.Model):
    id           = db.Column(db.Integer, primary_key=True)
    student_name = db.Column(db.String(200), default='O\'quvchi')
    lesson_title = db.Column(db.String(200), default='')
    total_score  = db.Column(db.Float, default=0)
    max_score    = db.Column(db.Float, default=0)
    answers_json = db.Column(db.Text, default='{}')
    submitted_at = db.Column(db.DateTime, default=datetime.utcnow)

# ─── Init DB ──────────────────────────────────────────────────────────────────

def init_db():
    os.makedirs(os.path.join(BASE_DIR, 'data'), exist_ok=True)
    with app.app_context():
        db.create_all()
        if Lesson.query.count() == 0:
            seed_demo()

def seed_demo():
    lesson = Lesson(title='Урок 9: Дни недели и время', subtitle='A1', order=1)
    db.session.add(lesson)
    db.session.flush()

    blocks_data = [
        (0, 'heading', {'text': 'ДНИ НЕДЕЛИ И ВРЕМЯ', 'level': 1, 'color': '#e63946', 'bg': ''}),
        (1, 'hr', {'color': '#e63946'}),
        (2, 'vocab', {
            'title': 'Новые слова', 'bar_color': '#457b9d',
            'items': [
                {'ru': 'понедельник', 'uz': 'dushanba',    'audio': ''},
                {'ru': 'вторник',     'uz': 'seshanba',    'audio': ''},
                {'ru': 'среда',       'uz': 'chorshanba',  'audio': ''},
                {'ru': 'четверг',     'uz': 'payshanba',   'audio': ''},
                {'ru': 'пятница',     'uz': 'juma',        'audio': ''},
                {'ru': 'суббота',     'uz': 'shanba',      'audio': ''},
                {'ru': 'воскресенье', 'uz': 'yakshanba',   'audio': ''},
                {'ru': 'сегодня',     'uz': 'bugun',       'audio': ''},
                {'ru': 'вчера',       'uz': 'kecha',       'audio': ''},
                {'ru': 'время',       'uz': 'vaqt',        'audio': ''},
            ]
        }),
        (3, 'fill_blank', {
            'title': 'Упражнение 1', 'bar_color': '#2a9d8f',
            'instruction': 'Поставьте слово «час» в подходящую форму',
            'items': [
                {'pre': 'Сейчас четыре',  'answer': 'часа',   'post': 'дня.'},
                {'pre': 'Сейчас восемь',  'answer': 'часов',  'post': 'вечера.'},
                {'pre': 'Сейчас 1',       'answer': 'час',    'post': 'ночи.'},
                {'pre': 'Сейчас десять',  'answer': 'часов',  'post': 'утра.'},
            ]
        }),
        (4, 'quiz', {
            'title': 'Мини-тест', 'bar_color': '#6a4c93',
            'questions': [
                {'q': 'Какой день идёт после среды?',
                 'options': ['вторник','четверг','пятница','суббота'], 'correct': 1},
                {'q': 'Первый день рабочей недели — это:',
                 'options': ['воскресенье','суббота','понедельник','пятница'], 'correct': 2},
            ]
        }),
    ]
    for order, btype, bdata in blocks_data:
        b = Block(lesson_id=lesson.id, type=btype, order=order,
                  data=json.dumps(bdata, ensure_ascii=False))
        db.session.add(b)
    db.session.commit()

# ─── API: Rol (session) ───────────────────────────────────────────────────────

@app.route('/api/role', methods=['GET'])
def get_role():
    return jsonify({'role': session.get('role', None)})

@app.route('/api/role/set', methods=['POST'])
def set_role():
    d = request.json or {}
    role = d.get('role', 'student')
    if role == 'teacher':
        pwd = d.get('password', '')
        if hashlib.sha256(pwd.encode()).hexdigest() != TEACHER_PASS_HASH:
            return jsonify({'ok': False, 'error': 'Parol noto\'g\'ri'}), 401
    session['role'] = role
    session.permanent = True
    return jsonify({'ok': True, 'role': role})

@app.route('/api/role/logout', methods=['POST'])
def logout():
    session.pop('role', None)
    return jsonify({'ok': True})

# ─── API: Lessons ─────────────────────────────────────────────────────────────

@app.route('/api/lessons', methods=['GET'])
def get_lessons():
    lessons = Lesson.query.order_by(Lesson.order).all()
    return jsonify([{
        'id': l.id, 'title': l.title, 'subtitle': l.subtitle,
        'order': l.order, 'block_count': len(l.blocks)
    } for l in lessons])

@app.route('/api/lessons', methods=['POST'])
def create_lesson():
    d = request.json
    max_order = db.session.query(db.func.max(Lesson.order)).scalar() or 0
    lesson = Lesson(title=d['title'], subtitle=d.get('subtitle', ''), order=max_order + 1)
    db.session.add(lesson)
    db.session.commit()
    return jsonify({'id': lesson.id, 'title': lesson.title})

@app.route('/api/lessons/<int:lid>', methods=['PUT'])
def update_lesson(lid):
    lesson = Lesson.query.get_or_404(lid)
    d = request.json
    if 'title' in d:    lesson.title    = d['title']
    if 'subtitle' in d: lesson.subtitle = d['subtitle']
    db.session.commit()
    return jsonify({'ok': True})

@app.route('/api/lessons/<int:lid>', methods=['DELETE'])
def delete_lesson(lid):
    lesson = Lesson.query.get_or_404(lid)
    db.session.delete(lesson)
    db.session.commit()
    return jsonify({'ok': True})

@app.route('/api/lessons/<int:lid>/duplicate', methods=['POST'])
def duplicate_lesson(lid):
    orig = Lesson.query.get_or_404(lid)
    max_order = db.session.query(db.func.max(Lesson.order)).scalar() or 0
    new_l = Lesson(title=orig.title + ' (копия)', subtitle=orig.subtitle, order=max_order + 1)
    db.session.add(new_l)
    db.session.flush()
    for b in orig.blocks:
        nb = Block(lesson_id=new_l.id, type=b.type, order=b.order, data=b.data)
        db.session.add(nb)
    db.session.commit()
    return jsonify({'id': new_l.id, 'title': new_l.title})

# ─── API: Blocks ──────────────────────────────────────────────────────────────

@app.route('/api/lessons/<int:lid>/blocks', methods=['GET'])
def get_blocks(lid):
    blocks = Block.query.filter_by(lesson_id=lid).order_by(Block.order).all()
    return jsonify([b.to_dict() for b in blocks])

@app.route('/api/blocks', methods=['POST'])
def create_block():
    d = request.json
    max_order = db.session.query(db.func.max(Block.order)) \
                    .filter(Block.lesson_id == d['lesson_id']).scalar() or 0
    block = Block(
        lesson_id=d['lesson_id'],
        type=d['type'],
        order=d.get('order', max_order + 1),
        data=json.dumps(d.get('data', {}), ensure_ascii=False)
    )
    db.session.add(block)
    db.session.commit()
    return jsonify(block.to_dict())

@app.route('/api/blocks/<int:bid>', methods=['PUT'])
def update_block(bid):
    block = Block.query.get_or_404(bid)
    d = request.json
    if 'data' in d:  block.data  = json.dumps(d['data'], ensure_ascii=False)
    if 'order' in d: block.order = d['order']
    db.session.commit()
    return jsonify(block.to_dict())

@app.route('/api/blocks/<int:bid>', methods=['DELETE'])
def delete_block(bid):
    block = Block.query.get_or_404(bid)
    db.session.delete(block)
    db.session.commit()
    return jsonify({'ok': True})

@app.route('/api/blocks/reorder', methods=['POST'])
def reorder_blocks():
    for item in request.json:
        Block.query.filter_by(id=item['id']).update({'order': item['order']})
    db.session.commit()
    return jsonify({'ok': True})

# ─── API: Progress ────────────────────────────────────────────────────────────

@app.route('/api/progress/<int:bid>', methods=['GET'])
def get_progress(bid):
    p = StudentProgress.query.filter_by(block_id=bid).first()
    if not p: return jsonify({'answers': {}, 'score': 0})
    return jsonify({'answers': json.loads(p.answers), 'score': p.score})

@app.route('/api/progress/<int:bid>', methods=['POST'])
def save_progress(bid):
    d = request.json
    p = StudentProgress.query.filter_by(block_id=bid).first()
    if not p:
        p = StudentProgress(block_id=bid)
        db.session.add(p)
    p.answers = json.dumps(d.get('answers', {}), ensure_ascii=False)
    p.score   = d.get('score', 0)
    db.session.commit()
    return jsonify({'ok': True})

# ─── API: .urok Export ────────────────────────────────────────────────────────

@app.route('/api/lessons/<int:lid>/export', methods=['GET'])
def export_lesson(lid):
    """Darsni shifrlangan .urok fayl sifatida qaytaradi"""
    lesson = Lesson.query.get_or_404(lid)
    blocks = Block.query.filter_by(lesson_id=lid).order_by(Block.order).all()

    payload = {
        'format':    'urok',
        'version':   UROK_VERSION,
        'exported':  datetime.utcnow().isoformat(),
        'lesson': {
            'title':    lesson.title,
            'subtitle': lesson.subtitle,
        },
        'blocks': [
            {'type': b.type, 'order': b.order, 'data': json.loads(b.data or '{}')}
            for b in blocks
        ]
    }

    encoded = encode_urok(payload)
    # Fayl nomi
    safe_title = ''.join(c if c.isalnum() or c in '-_ ' else '_' for c in lesson.title)[:40]
    fname = f"{safe_title}.urok"

    from flask import Response
    return Response(
        encoded,
        mimetype='application/octet-stream',
        headers={'Content-Disposition': f'attachment; filename="{fname}"'}
    )

# ─── API: .urok Import (o'quvchi uchun) ─────────────────────────────────────

@app.route('/api/urok/decode', methods=['POST'])
def decode_urok_api():
    """Frontend .urok faylni yuboradi, JSON payload qaytaradi (o'quvchi rejimi)"""
    f = request.files.get('file')
    if not f:
        # JSON body orqali ham qabul qilish
        d = request.json or {}
        b64 = d.get('data', '')
    else:
        b64 = f.read().decode('ascii').strip()

    try:
        payload = decode_urok(b64)
    except Exception as e:
        return jsonify({'error': str(e)}), 400

    return jsonify({'ok': True, 'payload': payload})

@app.route('/api/urok/decode-teacher', methods=['POST'])
def decode_urok_teacher():
    """O'qituvchi uchun: parol tekshirib, keyin decode qiladi"""
    d = request.json or {}
    pwd = d.get('password', '')
    if hashlib.sha256(pwd.encode()).hexdigest() != TEACHER_PASS_HASH:
        return jsonify({'ok': False, 'error': 'Parol noto\'g\'ri'}), 401

    b64 = d.get('data', '')
    try:
        payload = decode_urok(b64)
    except Exception as e:
        return jsonify({'error': str(e)}), 400

    return jsonify({'ok': True, 'payload': payload})

# ─── API: Natijalarni saqlash ─────────────────────────────────────────────────

@app.route('/api/results', methods=['POST'])
def save_result():
    """O'quvchi .urok natija faylini serverga yuboradi"""
    d = request.json or {}
    result = StudentResult(
        student_name = d.get('student_name', 'O\'quvchi'),
        lesson_title = d.get('lesson_title', ''),
        total_score  = d.get('total_score', 0),
        max_score    = d.get('max_score', 0),
        answers_json = json.dumps(d.get('answers', {}), ensure_ascii=False),
    )
    db.session.add(result)
    db.session.commit()
    return jsonify({'ok': True, 'id': result.id})

@app.route('/api/results', methods=['GET'])
def get_results():
    """O'qituvchi barcha natijalarni ko'radi"""
    results = StudentResult.query.order_by(StudentResult.submitted_at.desc()).all()
    return jsonify([{
        'id':           r.id,
        'student_name': r.student_name,
        'lesson_title': r.lesson_title,
        'total_score':  r.total_score,
        'max_score':    r.max_score,
        'pct':          round(r.total_score / r.max_score * 100) if r.max_score else 0,
        'answers':      json.loads(r.answers_json or '{}'),
        'submitted_at': r.submitted_at.strftime('%Y-%m-%d %H:%M'),
    } for r in results])

@app.route('/api/results/<int:rid>', methods=['DELETE'])
def delete_result(rid):
    r = StudentResult.query.get_or_404(rid)
    db.session.delete(r)
    db.session.commit()
    return jsonify({'ok': True})

# ─── Upload ───────────────────────────────────────────────────────────────────

@app.route('/api/upload/audio', methods=['POST'])
def upload_audio():
    f = request.files.get('file')
    if not f: return jsonify({'error': 'no file'}), 400
    audio_dir = os.path.join(BASE_DIR, 'static', 'audio')
    os.makedirs(audio_dir, exist_ok=True)
    fname = f'{datetime.utcnow().timestamp()}_{f.filename}'
    f.save(os.path.join(audio_dir, fname))
    return jsonify({'url': f'/static/audio/{fname}'})

@app.route('/api/upload/image', methods=['POST'])
def upload_image():
    f = request.files.get('file')
    if not f: return jsonify({'error': 'no file'}), 400
    img_dir = os.path.join(BASE_DIR, 'static', 'img')
    os.makedirs(img_dir, exist_ok=True)
    fname = f'{datetime.utcnow().timestamp()}_{f.filename}'
    f.save(os.path.join(img_dir, fname))
    return jsonify({'url': f'/static/img/{fname}'})

# ─── Pages ────────────────────────────────────────────────────────────────────

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/static/<path:filename>')
def static_files(filename):
    return send_from_directory(os.path.join(BASE_DIR, 'static'), filename)

if __name__ == '__main__':
    init_db()
    print('\n🚀  LangLearn ishga tushdi!  →  http://127.0.0.1:5000\n')
    app.run(debug=True, port=5000)
