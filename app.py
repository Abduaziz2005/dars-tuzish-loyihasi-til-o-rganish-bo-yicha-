from flask import Flask, render_template, request, jsonify, send_from_directory
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
import json, os, copy

app = Flask(__name__)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{BASE_DIR}/data/langlearn.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SECRET_KEY'] = 'langlearn-secret-2024'

db = SQLAlchemy(app)

# ─── Models ───────────────────────────────────────────────────────────────────

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
    type       = db.Column(db.String(50), nullable=False)   # heading|vocab|exercise|image|hr|audio_text|crossword|match|fill_blank|quiz|dialog|table
    order      = db.Column(db.Integer, default=0)
    data       = db.Column(db.Text, default='{}')           # JSON payload
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

# ─── Init DB ──────────────────────────────────────────────────────────────────

def init_db():
    os.makedirs('data', exist_ok=True)
    with app.app_context():
        db.create_all()
        if Lesson.query.count() == 0:
            seed_demo()

def seed_demo():
    lesson = Lesson(title='Урок 9: Дни недели и время', subtitle='A1', order=1)
    db.session.add(lesson)
    db.session.flush()

    blocks_data = [
        (0, 'heading', {'text': 'ДНИ НЕДЕЛИ И ВРЕМЯ', 'level': 1,
                        'color': '#e63946', 'bg': ''}),
        (1, 'hr', {'color': '#e63946'}),
        (2, 'vocab', {
            'title': 'Новые слова', 'title_color': '#1d3557',
            'bar_color': '#457b9d',
            'items': [
                {'ru': 'понедельник', 'uz': '', 'audio': ''},
                {'ru': 'вторник',     'uz': '', 'audio': ''},
                {'ru': 'среда',       'uz': '', 'audio': ''},
                {'ru': 'четверг',     'uz': '', 'audio': ''},
                {'ru': 'пятница',     'uz': '', 'audio': ''},
                {'ru': 'суббота',     'uz': '', 'audio': ''},
                {'ru': 'воскресенье', 'uz': '', 'audio': ''},
                {'ru': 'сегодня',     'uz': '', 'audio': ''},
                {'ru': 'вчера',       'uz': '', 'audio': ''},
                {'ru': 'время',       'uz': '', 'audio': ''},
            ]
        }),
        (3, 'hr', {'color': '#e63946'}),
        (4, 'dialog', {
            'title': 'Диалог 1',
            'lines': [
                {'speaker': 'A', 'text': '— Какой сегодня день недели?'},
                {'speaker': 'B', 'text': '— Сегодня вторник.'},
                {'speaker': 'A', 'text': '— Какой день недели был вчера?'},
                {'speaker': 'B', 'text': '— Вчера был понедельник.'},
            ]
        }),
        (5, 'fill_blank', {
            'title': 'Упражнение 1',
            'bar_color': '#2a9d8f',
            'instruction': 'Поставьте слово «час» в подходящую форму',
            'items': [
                {'pre': 'Сейчас четыре', 'answer': 'часа', 'post': 'дня.'},
                {'pre': 'Сейчас восемь', 'answer': 'часов', 'post': 'вечера.'},
                {'pre': 'Сейчас 1',      'answer': 'час',   'post': 'ночи.'},
                {'pre': 'Сейчас десять', 'answer': 'часов', 'post': 'утра.'},
                {'pre': 'Сейчас три',    'answer': 'часа',  'post': 'ночи.'},
            ]
        }),
        (6, 'match', {
            'title': 'Упражнение: Соедини дни',
            'bar_color': '#e76f51',
            'pairs': [
                {'left': 'понедельник', 'right': 'Monday'},
                {'left': 'вторник',     'right': 'Tuesday'},
                {'left': 'среда',       'right': 'Wednesday'},
                {'left': 'четверг',     'right': 'Thursday'},
                {'left': 'пятница',     'right': 'Friday'},
                {'left': 'суббота',     'right': 'Saturday'},
                {'left': 'воскресенье', 'right': 'Sunday'},
            ]
        }),
        (7, 'quiz', {
            'title': 'Мини-тест',
            'bar_color': '#6a4c93',
            'questions': [
                {'q': 'Какой день идёт после среды?',
                 'options': ['вторник','четверг','пятница','суббота'],
                 'correct': 1},
                {'q': 'Как сказать 8 часов вечера?',
                 'options': ['8 часа вечера','8 часов вечера','8 час вечера','8 часов утра'],
                 'correct': 1},
                {'q': 'Первый день рабочей недели — это:',
                 'options': ['воскресенье','суббота','понедельник','пятница'],
                 'correct': 2},
            ]
        }),
    ]

    for order, btype, bdata in blocks_data:
        b = Block(lesson_id=lesson.id, type=btype, order=order,
                  data=json.dumps(bdata, ensure_ascii=False))
        db.session.add(b)
    db.session.commit()

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
    lesson = Lesson(title=d['title'], subtitle=d.get('subtitle',''),
                    order=max_order+1)
    db.session.add(lesson)
    db.session.commit()
    return jsonify({'id': lesson.id, 'title': lesson.title})

@app.route('/api/lessons/<int:lid>', methods=['PUT'])
def update_lesson(lid):
    lesson = Lesson.query.get_or_404(lid)
    d = request.json
    if 'title' in d: lesson.title = d['title']
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
    new_l = Lesson(title=orig.title + ' (копия)', subtitle=orig.subtitle,
                   order=max_order+1)
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
    max_order = db.session.query(db.func.max(Block.order))\
                  .filter(Block.lesson_id==d['lesson_id']).scalar() or 0
    block = Block(
        lesson_id = d['lesson_id'],
        type      = d['type'],
        order     = d.get('order', max_order+1),
        data      = json.dumps(d.get('data', {}), ensure_ascii=False)
    )
    db.session.add(block)
    db.session.commit()
    return jsonify(block.to_dict())

@app.route('/api/blocks/<int:bid>', methods=['PUT'])
def update_block(bid):
    block = Block.query.get_or_404(bid)
    d = request.json
    if 'data' in d:
        block.data = json.dumps(d['data'], ensure_ascii=False)
    if 'order' in d:
        block.order = d['order']
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
    items = request.json  # [{id, order}, ...]
    for item in items:
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

# ─── Upload audio ─────────────────────────────────────────────────────────────

@app.route('/api/upload/audio', methods=['POST'])
def upload_audio():
    f = request.files.get('file')
    if not f: return jsonify({'error': 'no file'}), 400
    os.makedirs('static/audio', exist_ok=True)
    fname = f'{datetime.utcnow().timestamp()}_{f.filename}'
    path = f'static/audio/{fname}'
    f.save(path)
    return jsonify({'url': f'/static/audio/{fname}'})

@app.route('/api/upload/image', methods=['POST'])
def upload_image():
    f = request.files.get('file')
    if not f: return jsonify({'error': 'no file'}), 400
    os.makedirs('static/img', exist_ok=True)
    fname = f'{datetime.utcnow().timestamp()}_{f.filename}'
    path = f'static/img/{fname}'
    f.save(path)
    return jsonify({'url': f'/static/img/{fname}'})

# ─── Pages ────────────────────────────────────────────────────────────────────

@app.route('/')
def index():
    return send_from_directory('templates', 'index.html')

@app.route('/static/<path:filename>')
def static_files(filename):
    return send_from_directory('static', filename)

if __name__ == '__main__':
    init_db()
    print('\n🚀  LangLearn ishga tushdi!  →  http://127.0.0.1:5000\n')
    app.run(debug=True, port=5000)
