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

# ─── Models ───────────────────────────────────────────────────────────

db = SQLAlchemy(app)

class User(db.Model):
    """Talaba / O'qituvchi"""
    id         = db.Column(db.Integer, primary_key=True)
    name       = db.Column(db.String(200), nullable=False)
    email      = db.Column(db.String(200), unique=True, nullable=False)
    role       = db.Column(db.String(20), default='student')  # 'student' yoki 'teacher'
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relationship
    chat_messages = db.relationship('ChatMessage', backref='user', lazy=True, cascade='all, delete-orphan')
    progress = db.relationship('UserProgress', backref='user', lazy=True, cascade='all, delete-orphan')

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
    """Talabaning har bir blok uchun progres"""
    id         = db.Column(db.Integer, primary_key=True)
    user_id    = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    block_id   = db.Column(db.Integer, db.ForeignKey('block.id'), nullable=False)
    answers    = db.Column(db.Text, default='{}')
    score      = db.Column(db.Float, default=0)
    max_score  = db.Column(db.Float, default=100)
    completed  = db.Column(db.Boolean, default=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationship
    user = db.relationship('User', backref='block_progress')
    block = db.relationship('Block')

class UserProgress(db.Model):
    """Talabaning jami taraqqiyoti"""
    id         = db.Column(db.Integer, primary_key=True)
    user_id    = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    lesson_id  = db.Column(db.Integer, db.ForeignKey('lesson.id'), nullable=False)
    score      = db.Column(db.Float, default=0)
    max_score  = db.Column(db.Float, default=0)
    completed  = db.Column(db.Boolean, default=False)
    started_at = db.Column(db.DateTime, default=datetime.utcnow)
    completed_at = db.Column(db.DateTime, nullable=True)

class StudentResult(db.Model):
    id           = db.Column(db.Integer, primary_key=True)
    student_name = db.Column(db.String(200), default='O\'quvchi')
    lesson_title = db.Column(db.String(200), default='')
    total_score  = db.Column(db.Float, default=0)
    max_score    = db.Column(db.Float, default=0)
    answers_json = db.Column(db.Text, default='{}')
    submitted_at = db.Column(db.DateTime, default=datetime.utcnow)

class ChatMessage(db.Model):
    """O'qituvchi va talaba o'rtasidagi chat xabar"""
    id         = db.Column(db.Integer, primary_key=True)
    user_id    = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    message    = db.Column(db.Text, nullable=False)
    message_type = db.Column(db.String(20), default='text')  # 'text', 'file', 'lesson'
    lesson_id  = db.Column(db.Integer, db.ForeignKey('lesson.id'), nullable=True)
    is_teacher_reply = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

# ─── Init DB ──────────────────────────────────────────────────────────

def init_db():
    os.makedirs(os.path.join(BASE_DIR, 'data'), exist_ok=True)
    with app.app_context():
        db.create_all()
        if Lesson.query.count() == 0:
            seed_demo()

def seed_demo():
    # Dars 1: СТУДЕНТ! (Greetings & Introduction - Red Kalinka A1)
    lesson1 = Lesson(title='Дарс 1: СТУДЕНТ!', subtitle='A1', order=1)
    db.session.add(lesson1)
    db.session.flush()

    blocks_data_1 = [
        (0, 'heading', {'text': 'СТУДЕНТ! Salomlashish va Tanishish', 'level': 1, 'color': '#e63946', 'bg': ''}),
        (1, 'hr', {'color': '#e63946'}),
        
        # Listening Comprehension - NEW
        (2, 'listening', {
            'title': '👂 Tinglash Mashqlari: Salomlashish',
            'questions': [
                {
                    'audio': '',
                    'question': '1. Odamning ismi kimdir?',
                    'options': ['Anton', 'Natasha', 'Petr', 'Elena'],
                    'correct': 1
                },
                {
                    'audio': '',
                    'question': '2. Gapda "kak dela?" ning ma\'nosi?',
                    'options': ['Xayr', 'Qanday ekan?', 'Rahmat', 'Salom'],
                    'correct': 1
                }
            ]
        }),
        
        # Новые слова
        (3, 'vocab', {
            'title': 'Янги сўзлар (Новые слова)', 'bar_color': '#457b9d',
            'items': [
                {'ru': 'Привет!', 'uz': 'Salom!', 'audio': ''},
                {'ru': 'Доброе утро!', 'uz': 'Xayrli tong!', 'audio': ''},
                {'ru': 'Добрый день!', 'uz': 'Xayrli kun!', 'audio': ''},
                {'ru': 'Добрый вечер!', 'uz': 'Xayrli kech!', 'audio': ''},
                {'ru': 'тоже', 'uz': 'ham', 'audio': ''},
                {'ru': 'очень', 'uz': 'juda', 'audio': ''},
                {'ru': 'Как дела?', 'uz': 'Qalaysan?', 'audio': ''},
                {'ru': 'Как у тебя дела?', 'uz': 'Sening qalaying?', 'audio': ''},
                {'ru': 'Как у вас дела?', 'uz': 'Sizning qalaying?', 'audio': ''},
                {'ru': 'А у тебя?', 'uz': 'Seningcha?', 'audio': ''},
                {'ru': 'А у вас?', 'uz': 'Sizingcha?', 'audio': ''},
                {'ru': 'отлично', 'uz': 'juda yaxshi', 'audio': ''},
                {'ru': 'хорошо - плохо', 'uz': 'yaxshi - yomon', 'audio': ''},
                {'ru': 'нормально', 'uz': 'oddiy', 'audio': ''},
                {'ru': 'пока', 'uz': 'xayr', 'audio': ''},
                {'ru': 'студент', 'uz': 'talaba', 'audio': ''},
                {'ru': 'студентка', 'uz': 'talaba (ayol)', 'audio': ''},
                {'ru': 'спасибо', 'uz': 'rahmat', 'audio': ''},
                {'ru': 'Как вас зовут?', 'uz': 'Ismingiz nima?', 'audio': ''},
                {'ru': 'Меня зовут...', 'uz': 'Mening ismim...', 'audio': ''},
                {'ru': 'я', 'uz': 'men', 'audio': ''},
                {'ru': 'ты', 'uz': 'sen', 'audio': ''},
                {'ru': 'он', 'uz': 'u', 'audio': ''},
                {'ru': 'она', 'uz': 'u (ayol)', 'audio': ''},
                {'ru': 'оно', 'uz': 'u (jansiz)', 'audio': ''},
                {'ru': 'мы', 'uz': 'biz', 'audio': ''},
                {'ru': 'вы', 'uz': 'siz', 'audio': ''},
                {'ru': 'они', 'uz': 'ular', 'audio': ''},
            ]
        }),
        
        # Диалог 1
        (4, 'dialog', {
            'title': 'Диалог 1 (Один - Один): Salomlashish',
            'lines': [
                {'speaker': 'A', 'text': 'Привет, Антон!'},
                {'speaker': 'B', 'text': 'Привёт, Наташа!'},
                {'speaker': 'A', 'text': 'Как дела?'},
                {'speaker': 'B', 'text': 'Спасибо, хорошо. А у тебя?'},
                {'speaker': 'A', 'text': 'Тоже хорошо.'},
                {'speaker': 'B', 'text': 'Пока.'},
                {'speaker': 'A', 'text': 'Пока.'},
            ]
        }),
        
        # Диалог 2
        (5, 'dialog', {
            'title': 'Диалог 2 (Два): Rasmiy salomlashish',
            'lines': [
                {'speaker': 'A', 'text': 'Привёт, Катя!'},
                {'speaker': 'B', 'text': 'Доброе утро, Саша!'},
                {'speaker': 'A', 'text': 'Как дела?'},
                {'speaker': 'B', 'text': 'Нормально. А у тебя?'},
                {'speaker': 'A', 'text': 'Тоже нормально.'},
                {'speaker': 'B', 'text': 'Пока!'},
                {'speaker': 'A', 'text': 'Пока!'},
            ]
        }),
        
        # Грамматика: Таблица местоимений
        (6, 'table', {
            'title': 'Грамматика: Местоимения (Hamma kelishdagi)',
            'headers': ['Именительный падеж', 'Винительный падеж (Объект)', 'Перевод на Ўзбекча'],
            'rows': [
                ['я', 'меня', 'men'],
                ['ты', 'тебя', 'sen'],
                ['он', 'его', 'u (erkak)'],
                ['она', 'её', 'u (ayol)'],
                ['оно', 'его', 'u (jansiz)'],
                ['мы', 'нас', 'biz'],
                ['вы', 'вас', 'siz'],
                ['они', 'их', 'ular'],
            ]
        }),
        
        # Упражнение 1: Заполнение пропусков
        (7, 'fill_blank', {
            'title': 'Машқ 1: Сўзни то\'лдириб чиқинг',
            'bar_color': '#2a9d8f',
            'instruction': 'Тўғри жавобни танланг:',
            'items': [
                {'pre': '- Привет!', 'answer': 'Привет', 'post': '!'},
                {'pre': '- Как дела?', 'answer': 'Хорошо', 'post': '.'},
                {'pre': '- Спасибо,', 'answer': 'спасибо', 'post': '. А у тебя?'},
                {'pre': '- Я студент,', 'answer': 'студентка', 'post': '.'},
            ]
        }),
        
        # Quiz
        (8, 'quiz', {
            'title': 'Мини-тест: Қайси варианти тўғри?',
            'bar_color': '#6a4c93',
            'questions': [
                {
                    'q': '1. "Привет" нинг маъноси қай варианты тўғри?',
                    'options': ['Xayrli kech!', 'Salom!', 'Rahmat', 'Xayr'],
                    'correct': 1
                },
                {
                    'q': '2. Рас шахсий сўзнинг номи (личное местоимение) қайси?',
                    'options': ['они', 'очень', 'студент', 'спасибо'],
                    'correct': 0
                },
                {
                    'q': '3. "Добрый день!" қай вақтда айтилади?',
                    'options': ['Тонг вақтида', 'Kun o\'rtasida', 'Кеч вақтида', 'Туни'],
                    'correct': 1
                },
                {
                    'q': '4. "Как у вас дела?" - бу қайси шакли сўз?',
                    'options': ['Rasmiy', 'Notаsmiy', 'Qimosiy', 'Ziyoiy'],
                    'correct': 0
                },
                {
                    'q': '5. "они" сўзининг маъноси?',
                    'options': ['u (erkak)', 'biz', 'ular', 'siz'],
                    'correct': 2
                },
            ]
        }),
        
        # Vocab timer
        (9, 'vocab_timer', {
            'title': 'Луғат вақти: Сўзларни ёдлаб олинг (120 сония)',
            'timer_sec': 120,
            'test_order': 'random',
            'test_dir': 'random',
            'items': [
                {'ru': 'Привет!', 'uz': 'Salom!'},
                {'ru': 'Доброе утро!', 'uz': 'Xayrli tong!'},
                {'ru': 'Добрый день!', 'uz': 'Xayrli kun!'},
                {'ru': 'Добрый вечер!', 'uz': 'Xayrli kech!'},
                {'ru': 'Как дела?', 'uz': 'Qalaysan?'},
                {'ru': 'спасибо', 'uz': 'rahmat'},
                {'ru': 'пока', 'uz': 'xayr'},
                {'ru': 'студент', 'uz': 'talaba'},
            ]
        }),
    ]
    
    for order, btype, bdata in blocks_data_1:
        b = Block(lesson_id=lesson1.id, type=btype, order=order,
                  data=json.dumps(bdata, ensure_ascii=False))
        db.session.add(b)
    
    db.session.commit()

# ─── API: Rol (session) ──────────────────────────────────────────────────────

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

# ─── API: Lessons ────────────────────────────────────────────────────────

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

# ─── API: Blocks ─────────────────────────────────────────────────────────

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

# ─── API: Progress Dashboard ────────────────────────────────────────────────

@app.route('/api/progress/dashboard', methods=['GET'])
def get_progress_dashboard():
    """Talabaning taraqqiyot paneli - barchaga ko'rinadi"""
    lessons = Lesson.query.order_by(Lesson.order).all()
    dashboard = []
    
    for lesson in lessons:
        blocks = Block.query.filter_by(lesson_id=lesson.id).all()
        total_score = 0
        max_score = 0
        completed = 0
        
        for block in blocks:
            prog = StudentProgress.query.filter_by(block_id=block.id).first()
            if prog:
                total_score += prog.score
                max_score += prog.max_score
                if prog.completed:
                    completed += 1
        
        dashboard.append({
            'lesson_id': lesson.id,
            'title': lesson.title,
            'subtitle': lesson.subtitle,
            'total_blocks': len(blocks),
            'completed_blocks': completed,
            'score': total_score,
            'max_score': max_score,
            'percentage': round(total_score / max_score * 100) if max_score > 0 else 0
        })
    
    return jsonify(dashboard)

@app.route('/api/progress/lesson/<int:lid>', methods=['GET'])
def get_lesson_progress(lid):
    """Bitta dars uchun detailed progress"""
    lesson = Lesson.query.get_or_404(lid)
    blocks = Block.query.filter_by(lesson_id=lid).order_by(Block.order).all()
    
    blocks_progress = []
    for block in blocks:
        prog = StudentProgress.query.filter_by(block_id=block.id).first()
        blocks_progress.append({
            'block_id': block.id,
            'block_type': block.type,
            'order': block.order,
            'score': prog.score if prog else 0,
            'max_score': prog.max_score if prog else 100,
            'completed': prog.completed if prog else False,
            'percentage': round(prog.score / prog.max_score * 100) if prog and prog.max_score > 0 else 0
        })
    
    return jsonify({
        'lesson': {'id': lesson.id, 'title': lesson.title},
        'blocks': blocks_progress
    })

@app.route('/api/progress/<int:bid>', methods=['GET'])
def get_progress(bid):
    """Bitta blok uchun progress"""
    p = StudentProgress.query.filter_by(block_id=bid).first()
    if not p: 
        return jsonify({'answers': {}, 'score': 0, 'max_score': 100, 'completed': False})
    return jsonify({
        'answers': json.loads(p.answers),
        'score': p.score,
        'max_score': p.max_score,
        'completed': p.completed
    })

@app.route('/api/progress/<int:bid>', methods=['POST'])
def save_progress(bid):
    """Blok natija saqlash"""
    d = request.json
    p = StudentProgress.query.filter_by(block_id=bid).first()
    if not p:
        p = StudentProgress(block_id=bid)
        db.session.add(p)
    
    p.answers = json.dumps(d.get('answers', {}), ensure_ascii=False)
    p.score = d.get('score', 0)
    p.max_score = d.get('max_score', 100)
    p.completed = d.get('completed', False)
    
    db.session.commit()
    return jsonify({'ok': True})

# ─── API: Chat (O'qituvchi va Talaba o'rtasidagi) ────────────────────────────

@app.route('/api/chat/messages', methods=['GET'])
def get_chat_messages():
    """Barcha chat xabarlarini olish"""
    messages = ChatMessage.query.order_by(ChatMessage.created_at).all()
    return jsonify([{
        'id': m.id,
        'user_name': m.user.name if m.user else 'Noma\'lum',
        'message': m.message,
        'message_type': m.message_type,
        'lesson_id': m.lesson_id,
        'is_teacher_reply': m.is_teacher_reply,
        'created_at': m.created_at.strftime('%Y-%m-%d %H:%M')
    } for m in messages])

@app.route('/api/chat/send', methods=['POST'])
def send_chat_message():
    """Yangi chat xabari yuborish"""
    d = request.json or {}
    
    # User yaratish yoki olish
    user_name = d.get('user_name', 'Noma\'lum')
    user_email = d.get('user_email', f'user_{secrets.token_hex(4)}@example.com')
    
    user = User.query.filter_by(email=user_email).first()
    if not user:
        user = User(name=user_name, email=user_email, role='student')
        db.session.add(user)
        db.session.flush()
    
    # Chat xabari saqlash
    msg = ChatMessage(
        user_id=user.id,
        message=d.get('message', ''),
        message_type=d.get('message_type', 'text'),
        lesson_id=d.get('lesson_id', None),
        is_teacher_reply=False
    )
    db.session.add(msg)
    db.session.commit()
    
    return jsonify({'ok': True, 'id': msg.id})

@app.route('/api/chat/reply/<int:msg_id>', methods=['POST'])
def reply_to_message(msg_id):
    """O'qituvchi javob berish"""
    d = request.json or {}
    
    # Parol tekshirish
    pwd = d.get('password', '')
    if hashlib.sha256(pwd.encode()).hexdigest() != TEACHER_PASS_HASH:
        return jsonify({'ok': False, 'error': 'Parol noto\'g\'ri'}), 401
    
    orig_msg = ChatMessage.query.get_or_404(msg_id)
    
    # O'qituvchi xabari
    reply_msg = ChatMessage(
        user_id=orig_msg.user_id,
        message=d.get('reply', ''),
        message_type='text',
        lesson_id=orig_msg.lesson_id,
        is_teacher_reply=True
    )
    db.session.add(reply_msg)
    db.session.commit()
    
    return jsonify({'ok': True, 'id': reply_msg.id})

@app.route('/api/chat/delete/<int:msg_id>', methods=['DELETE'])
def delete_chat_message(msg_id):
    """Chat xabarni o'chirish (faqat o'qituvchi)"""
    d = request.json or {}
    pwd = d.get('password', '')
    if hashlib.sha256(pwd.encode()).hexdigest() != TEACHER_PASS_HASH:
        return jsonify({'ok': False, 'error': 'Parol noto\'g\'ri'}), 401
    
    msg = ChatMessage.query.get_or_404(msg_id)
    db.session.delete(msg)
    db.session.commit()
    return jsonify({'ok': True})

# ─── Upload ──────────────────────────────────────────────────────────

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

@app.route('/api/upload/video', methods=['POST'])
def upload_video():
    f = request.files.get('file')
    if not f: return jsonify({'error': 'no file'}), 400
    vid_dir = os.path.join(BASE_DIR, 'static', 'video')
    os.makedirs(vid_dir, exist_ok=True)
    fname = f'{datetime.utcnow().timestamp()}_{f.filename}'
    f.save(os.path.join(vid_dir, fname))
    return jsonify({'url': f'/static/video/{fname}'})

# ─── API: .urok Export ───────────────────────────────────────────────────────

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

# ─── API: Results ─────────────────────────────────────────────────────────

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
    data = []
    for r in results:
        answers_raw = json.loads(r.answers_json or '{}')
        processed = {}
        for block_id, block_data in answers_raw.items():
            if isinstance(block_data, dict):
                b_type  = block_data.get('type', '')
                b_title = block_data.get('title', '')
                b_ans   = block_data.get('answers', {})
                b_score = block_data.get('score', 0)
                b_max   = block_data.get('max', 0)
                if b_type in ('vocab_timer', 'gen_test'):
                    rows = []
                    for q, v in b_ans.items():
                        if isinstance(v, dict):
                            rows.append({
                                'question':  q,
                                'given':     v.get('given', ''),
                                'correct':   v.get('correct', ''),
                                'is_correct':v.get('isCorrect', v.get('correct', '') == v.get('given', '')),
                            })
                    processed[block_id] = {
                        'type': b_type, 'title': b_title,
                        'score': b_score, 'max': b_max,
                        'rows': rows,
                        'answers': b_ans,
                    }
                else:
                    processed[block_id] = block_data
            else:
                processed[block_id] = block_data

        data.append({
            'id':           r.id,
            'student_name': r.student_name,
            'lesson_title': r.lesson_title,
            'total_score':  r.total_score,
            'max_score':    r.max_score,
            'pct':          round(r.total_score / r.max_score * 100) if r.max_score else 0,
            'answers':      processed,
            'submitted_at': r.submitted_at.strftime('%Y-%m-%d %H:%M'),
        })
    return jsonify(data)

@app.route('/api/results/<int:rid>', methods=['DELETE'])
def delete_result(rid):
    r = StudentResult.query.get_or_404(rid)
    db.session.delete(r)
    db.session.commit()
    return jsonify({'ok': True})

# ─── Pages ──────────────────────────────────────────────────────────

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
