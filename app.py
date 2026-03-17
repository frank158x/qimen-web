import json
import requests
import os
import sqlite3
from flask import Flask, request, render_template_string, jsonify
from lunar_python import Solar, Lunar, JieQi
import datetime

app = Flask(__name__)

# ==========================================
# --- 配置区域 ---
# ==========================================
DEEPSEEK_API_URL = "https://api.deepseek.com/chat/completions"
DEEPSEEK_API_KEY = "sk-8a9ff49b65bf4318bc9e8bdcb01a8491"  # 请替换为您申请的 Key

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
DB_NAME = os.path.join(BASE_DIR, 'qimen.db')


# ==========================================
# --- 数据库管理 (历史记录) ---
# ==========================================
def init_db():
    with sqlite3.connect(DB_NAME) as conn:
        conn.execute('''CREATE TABLE IF NOT EXISTS history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            summary TEXT,
            inputs TEXT,
            question TEXT,
            analysis TEXT
        )''')


def save_record(inputs, summary):
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute('INSERT INTO history (summary, inputs) VALUES (?, ?)',
                       (summary, json.dumps(inputs)))
        return cursor.lastrowid


def update_analysis(record_id, question, analysis):
    with sqlite3.connect(DB_NAME) as conn:
        conn.execute('UPDATE history SET question = ?, analysis = ? WHERE id = ?',
                     (question, analysis, record_id))


# 【新增】专门用于追加更新聊天记录的函数
def update_analysis_only(record_id, analysis):
    with sqlite3.connect(DB_NAME) as conn:
        conn.execute('UPDATE history SET analysis = ? WHERE id = ?',
                     (analysis, record_id))


def get_record(record_id):
    with sqlite3.connect(DB_NAME) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.execute('SELECT * FROM history WHERE id = ?', (record_id,))
        return cursor.fetchone()


def get_all_history():
    with sqlite3.connect(DB_NAME) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.execute('SELECT id, timestamp, summary, question FROM history ORDER BY id DESC')
        return [dict(row) for row in cursor.fetchall()]


def delete_record_db(record_id):
    with sqlite3.connect(DB_NAME) as conn:
        conn.execute('DELETE FROM history WHERE id = ?', (record_id,))


init_db()


# ==========================================
# 奇门遁甲核心算法类
# ==========================================
class QiMenModel:
    def __init__(self, year, month, day, hour, minute, longitude):
        self.year = year
        self.month = month
        self.day = day
        self.hour = hour
        self.minute = minute
        self.longitude = longitude

        self.GUA = {1: '坎', 2: '坤', 3: '震', 4: '巽', 5: '中', 6: '乾', 7: '兑', 8: '艮', 9: '离'}
        self.STEMS = ['甲', '乙', '丙', '丁', '戊', '己', '庚', '辛', '壬', '癸']
        self.BRANCHES = ['子', '丑', '寅', '卯', '辰', '巳', '午', '未', '申', '酉', '戌', '亥']
        self.PATH = [1, 8, 3, 4, 9, 2, 7, 6]
        self.STAR_ORIGIN = {'天蓬': 1, '天芮': 2, '天冲': 3, '天辅': 4, '天禽': 5, '天心': 6, '天柱': 7, '天任': 8,
                            '天英': 9}
        self.DOOR_ORIGIN = {'休门': 1, '死门': 2, '伤门': 3, '杜门': 4, '开门': 6, '惊门': 7, '生门': 8, '景门': 9}

        self.data = {}
        self.final_grid = {}
        self._calculate()

    def _get_xun_shou(self, gan, zhi):
        g_idx = self.STEMS.index(gan)
        z_idx = self.BRANCHES.index(zhi)
        diff = z_idx - g_idx
        if diff < 0: diff += 12
        head_zhi = self.BRANCHES[diff]
        mapping = {'子': '戊', '戌': '己', '申': '庚', '午': '辛', '辰': '壬', '寅': '癸'}
        return mapping[head_zhi]

    def _calculate(self):
        offset_min = (self.longitude - 120) * 4
        total_minutes = self.hour * 60 + self.minute + offset_min
        t_hour = int((total_minutes / 60) % 24)
        t_min = int(total_minutes % 60)

        solar_obj = Solar.fromYmdHms(self.year, self.month, self.day, t_hour, t_min, 0)
        lunar = Lunar.fromSolar(solar_obj)
        gz = lunar.getEightChar()

        self.gz_info = {
            'year': gz.getYear(), 'month': gz.getMonth(),
            'day': gz.getDay(), 'time': gz.getTime(),
            'day_gan': gz.getDayGan(), 'time_gan': gz.getTimeGan(),
            'day_xun_kong': lunar.getDayXunKong(),
            'time_xun_kong': lunar.getTimeXunKong()
        }

        self.data['time_info'] = {
            'solar': f"{self.year}-{self.month}-{self.day} {t_hour}:{t_min:02d} (真太阳时)",
            'gan_zhi': f"{gz.getYear()}年 {gz.getMonth()}月 {gz.getDay()}日 {gz.getTime()}时",
            'xun_kong': f"{lunar.getDayXunKong()} (日空) {lunar.getTimeXunKong()} (时空)"
        }

        prev_jie = lunar.getPrevJieQi(True)
        current_jie_qi = prev_jie.getName()

        JIE_QI_MAP = {
            '冬至': [1, 7, 4, 1], '小寒': [2, 8, 5, 1], '大寒': [3, 9, 6, 1],
            '立春': [8, 5, 2, 1], '雨水': [9, 6, 3, 1], '惊蛰': [1, 7, 4, 1],
            '春分': [3, 9, 6, 1], '清明': [4, 1, 7, 1], '谷雨': [5, 2, 8, 1],
            '立夏': [4, 1, 7, 1], '小满': [5, 2, 8, 1], '芒种': [6, 3, 9, 1],
            '夏至': [9, 3, 6, -1], '小暑': [8, 2, 5, -1], '大暑': [7, 1, 4, -1],
            '立秋': [2, 5, 8, -1], '处暑': [1, 4, 7, -1], '白露': [9, 3, 6, -1],
            '秋分': [7, 1, 4, -1], '寒露': [6, 9, 3, -1], '霜降': [5, 8, 2, -1],
            '立冬': [6, 9, 3, -1], '小雪': [5, 8, 2, -1], '大雪': [4, 7, 1, -1],
        }

        term_info = JIE_QI_MAP.get(current_jie_qi, [1, 1, 1, 1])
        day_zhi = gz.getDayZhi()
        yuan_map = {'子': 0, '午': 0, '卯': 0, '酉': 0, '寅': 1, '申': 1, '巳': 1, '亥': 1, '辰': 2, '戌': 2, '丑': 2,
                    '未': 2}
        yuan_idx = yuan_map[day_zhi]
        yuan_name = ['上元', '中元', '下元'][yuan_idx]

        ju_num = term_info[yuan_idx]
        dun_type = "阳" if term_info[3] == 1 else "阴"
        self.data['ju_info'] = f"{current_jie_qi} {yuan_name} {dun_type}遁{ju_num}局"

        instruments = ['戊', '己', '庚', '辛', '壬', '癸', '丁', '丙', '乙']
        di_pan = {}
        curr = ju_num
        for stem in instruments:
            di_pan[curr] = stem
            if dun_type == "阳":
                curr += 1
                if curr > 9: curr = 1
            else:
                curr -= 1
                if curr < 1: curr = 9

        time_gan = gz.getTimeGan()
        time_zhi = gz.getTimeZhi()
        xun_shou_stem = self._get_xun_shou(time_gan, time_zhi)

        xun_shou_loc = 0
        for k, v in di_pan.items():
            if v == xun_shou_stem:
                xun_shou_loc = k
                break

        check_loc = xun_shou_loc
        if check_loc == 5: check_loc = 2

        zhi_fu_star = [k for k, v in self.STAR_ORIGIN.items() if v == check_loc][0]
        zhi_shi_door = [k for k, v in self.DOOR_ORIGIN.items() if v == check_loc][0]

        self.data['leaders'] = f"旬首: {xun_shou_stem} | 值符: {zhi_fu_star} | 值使: {zhi_shi_door}"

        target_stem = time_gan
        if target_stem == '甲': target_stem = xun_shou_stem

        target_loc = 0
        for k, v in di_pan.items():
            if v == target_stem:
                target_loc = k
                break

        star_origin_idx = self.PATH.index(self.STAR_ORIGIN[zhi_fu_star])
        target_path_idx = self.PATH.index(target_loc) if target_loc != 5 else self.PATH.index(2)
        shift = target_path_idx - star_origin_idx

        tian_pan_stars = {}
        tian_pan_stems = {}
        for star, origin_loc in self.STAR_ORIGIN.items():
            if star == '天禽': continue
            origin_path_idx = self.PATH.index(origin_loc)
            new_path_idx = (origin_path_idx + shift) % 8
            new_loc = self.PATH[new_path_idx]
            tian_pan_stars[new_loc] = star
            stem_under_star = di_pan[origin_loc]
            tian_pan_stems[new_loc] = stem_under_star
            if star == '天芮':
                tian_pan_stars[new_loc] = "天芮(禽)"
                stem_center = di_pan[5]
                tian_pan_stems[new_loc] += "/" + stem_center

        gods_yang = ['值符', '螣蛇', '太阴', '六合', '白虎', '玄武', '九地', '九天']
        gods_yin = ['值符', '九天', '九地', '玄武', '白虎', '六合', '太阴', '螣蛇']
        gods_list = gods_yang if dun_type == "阳" else gods_yin
        zhifu_loc = target_loc if target_loc != 5 else 2
        zhifu_path_idx = self.PATH.index(zhifu_loc)
        shen_pan = {}
        for i, god in enumerate(gods_list):
            idx = (zhifu_path_idx + i) % 8
            loc = self.PATH[idx]
            shen_pan[loc] = god

        xun_map = {'戊': '子', '己': '戌', '庚': '申', '辛': '午', '壬': '辰', '癸': '寅'}
        xun_zhi = xun_map[xun_shou_stem]
        xun_zhi_idx = self.BRANCHES.index(xun_zhi)
        time_zhi_idx = self.BRANCHES.index(time_zhi)
        diff = time_zhi_idx - xun_zhi_idx
        if diff < 0: diff += 12

        zs_origin_loc = self.DOOR_ORIGIN[zhi_shi_door]
        if dun_type == "阳":
            zs_target_loc = zs_origin_loc + diff
            while zs_target_loc > 9: zs_target_loc -= 9
        else:
            zs_target_loc = zs_origin_loc - diff
            while zs_target_loc < 1: zs_target_loc += 9

        ren_pan = {}
        base_doors = ['休门', '生门', '伤门', '杜门', '景门', '死门', '惊门', '开门']
        base_locs = [1, 8, 3, 4, 9, 2, 7, 6]
        door_idx = base_doors.index(zhi_shi_door)
        if zs_target_loc == 5: zs_target_loc = 2
        loc_idx = base_locs.index(zs_target_loc)
        for i in range(8):
            curr_door = base_doors[(door_idx + i) % 8]
            curr_loc = base_locs[(loc_idx + i) % 8]
            ren_pan[curr_loc] = curr_door

        for i in range(1, 10):
            self.final_grid[i] = {
                'id': i, 'gua': self.GUA[i], 'di': di_pan.get(i, ''),
                'tian': tian_pan_stars.get(i, ''), 'tian_gan': tian_pan_stems.get(i, ''),
                'men': ren_pan.get(i, ''), 'shen': shen_pan.get(i, '')
            }
            if i == 5:
                self.final_grid[i]['tian'] = '';
                self.final_grid[i]['men'] = ''

    def get_analysis_data(self):
        ma_xing_map = {'申': '寅', '子': '寅', '辰': '寅', '寅': '申', '午': '申', '戌': '申', '亥': '巳', '卯': '巳',
                       '未': '巳', '巳': '亥', '酉': '亥', '丑': '亥'}
        time_zhi = self.gz_info['time'][1]
        ma_xing = ma_xing_map.get(time_zhi, '')
        palace_zhi_map = {1: ['子'], 8: ['丑', '寅'], 3: ['卯'], 4: ['辰', '巳'], 9: ['午'], 2: ['未', '申'], 7: ['酉'],
                          6: ['戌', '亥']}
        xun_kong_str = self.gz_info['day_xun_kong']
        palaces_data = {}
        for i in range(1, 10):
            if i == 5: continue
            p = self.final_grid[i]
            is_kong = any(z in xun_kong_str for z in palace_zhi_map.get(i, []))
            is_ma = ma_xing in palace_zhi_map.get(i, [])
            palaces_data[f"宫{i}"] = {
                "卦位": self.GUA[i], "八神": p['shen'], "九星": p['tian'],
                "八门": p['men'], "天盘干": p['tian_gan'], "地盘干": p['di'],
                "格局": f"{p['tian_gan'].split('/')[0]}+{p['di']}",
                "状态": {"空亡": is_kong, "驿马": is_ma}
            }
        return {
            "提问信息": {
                "求测时间": self.data['time_info']['gan_zhi'],
                "日干": self.gz_info['day_gan'], "时干": self.gz_info['time_gan'],
                "节气": self.data['ju_info'], "空亡": xun_kong_str, "驿马": ma_xing
            },
            "盘面数据": palaces_data
        }


# ==========================================
# AI 逻辑
# ==========================================
def generate_analysis_prompt(data, question):
    system_prompt = """你是一位精通《奇门遁甲》的易学专家。
分析步骤：
1. **用神选取**：根据问题锁定用神。
2. **宫位状态**：分析旺衰、空亡、驿马。
3. **吉凶组合**：解读星+门+神+格局。
4. **主客关系**：日干与时干/用神宫生克。
5. **结论建议**：明确吉凶，提供建议。
请用通俗易懂的语言，同时结合以上步骤为用户详细解盘。使用 Markdown 格式输出。"""
    user_prompt = f"【排盘数据】:\n{json.dumps(data, ensure_ascii=False, indent=2)}\n\n【用户问题】:\n\"{question}\""
    return [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}]


def call_deepseek_api(messages):
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {DEEPSEEK_API_KEY}"}
    payload = {"model": "deepseek-chat", "messages": messages, "temperature": 1.3, "stream": False}
    try:
        response = requests.post(DEEPSEEK_API_URL, headers=headers, json=payload, timeout=60)
        response.raise_for_status()
        return response.json()['choices'][0]['message']['content']
    except Exception as e:
        return f"AI 连接失败: {str(e)}"


# ==========================================
# HTML 生成器
# ==========================================
def generate_grid_html(model):
    grid_items = ""
    order = [4, 9, 2, 3, 5, 7, 8, 1, 6]
    for idx in order:
        cell = model.final_grid[idx]
        extra_cls = "center-palace" if idx == 5 else ""
        grid_items += f"""
        <div class="palace p-{idx} {extra_cls}">
            <div class="palace-bg">{model.GUA[idx]}</div>
            <div class="element-group">
                <div class="top-row">
                    <div class="god">{cell['shen']}</div>
                    <div class="stems"><span class="tian-stem">{cell['tian_gan']}</span><span class="di-stem">{cell['di']}</span></div>
                </div>
                <div class="bottom-row"><div class="star">{cell['tian']}</div><div class="door">{cell['men']}</div></div>
            </div>
        </div>"""
    info = model.data
    return f"""
    <div class="result-container">
        <div class="info-card">
            <div class="info-item"><span class="info-label">真太阳时</span><span class="info-value">{info['time_info']['solar'].split(' ')[1]}</span></div>
            <div class="info-item"><span class="info-label">四柱</span><span class="info-value">{info['time_info']['gan_zhi']}</span></div>
            <div class="info-item"><span class="info-label">格局</span><span class="info-value">{info['ju_info']}</span></div>
            <div class="info-item"><span class="info-label">旬空</span><span class="info-value">{info['time_info']['xun_kong'].split(' ')[0]}</span></div>
            <div class="highlight-row">{info['leaders']}</div>
        </div>
        <div class="qimen-grid">{grid_items}</div>
    </div>"""


# ==========================================
# Flask 路由
# ==========================================
@app.route('/', methods=['GET', 'POST'])
def home():
    now = datetime.datetime.now()
    default_vals = {'year': now.year, 'month': now.month, 'day': now.day, 'hour': now.hour, 'minute': now.minute,
                    'lon': 120.0}
    result_html = ""
    current_record_id = ""
    history_question = ""
    history_analysis = ""

    js_content = ""
    try:
        with open('marked.min.js', 'r', encoding='utf-8') as f:
            js_content = f.read()
    except:
        pass

    if request.method == 'POST':
        try:
            inputs = {
                'year': int(request.form.get('year')),
                'month': int(request.form.get('month')),
                'day': int(request.form.get('day')),
                'hour': int(request.form.get('hour')),
                'minute': int(request.form.get('minute')),
                'lon': float(request.form.get('lon'))
            }

            model = QiMenModel(
                year=inputs['year'],
                month=inputs['month'],
                day=inputs['day'],
                hour=inputs['hour'],
                minute=inputs['minute'],
                longitude=inputs['lon']
            )

            result_html = generate_grid_html(model)
            default_vals = inputs

            summary = f"{model.data['time_info']['gan_zhi']} {model.data['ju_info']}"
            current_record_id = save_record(inputs, summary)

        except Exception as e:
            result_html = f"<div class='error-box'>排盘错误: {str(e)}</div>"

    elif request.args.get('history_id'):
        try:
            record = get_record(request.args.get('history_id'))
            if record:
                inputs = json.loads(record['inputs'])

                model = QiMenModel(
                    year=inputs['year'],
                    month=inputs['month'],
                    day=inputs['day'],
                    hour=inputs['hour'],
                    minute=inputs['minute'],
                    longitude=inputs['lon']
                )

                result_html = generate_grid_html(model)
                default_vals = inputs
                current_record_id = record['id']
                history_question = record['question'] if record['question'] else ""
                history_analysis = record['analysis'] if record['analysis'] else ""
        except Exception as e:
            result_html = f"<div class='error-box'>加载历史错误: {str(e)}</div>"

    return render_template_string(HTML_TEMPLATE, result=result_html, v=default_vals,
                                  marked_js=js_content, record_id=current_record_id,
                                  h_q=history_question, h_a=history_analysis)


@app.route('/analyze', methods=['POST'])
def analyze():
    try:
        data = request.json
        model = QiMenModel(
            year=int(data['year']),
            month=int(data['month']),
            day=int(data['day']),
            hour=int(data['hour']),
            minute=int(data['minute']),
            longitude=float(data['lon'])
        )
        analysis_data = model.get_analysis_data()
        question = data.get('question', '')

        messages = generate_analysis_prompt(analysis_data, question)
        ai_response = call_deepseek_api(messages)

        # 将AI回复加入历史
        messages.append({"role": "assistant", "content": ai_response})

        if data.get('record_id'):
            # 这里改为将完整的消息数组存储进去，以便后续多轮对话可以复原
            update_analysis(data['record_id'], question, json.dumps(messages, ensure_ascii=False))

        return jsonify({'status': 'success', 'messages': messages})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)})


# 【新增】多轮聊天追问路由
@app.route('/chat', methods=['POST'])
def chat_followup():
    try:
        data = request.json
        messages = data.get('messages', [])
        question = data.get('question', '')
        record_id = data.get('record_id')

        messages.append({"role": "user", "content": question})
        ai_response = call_deepseek_api(messages)
        messages.append({"role": "assistant", "content": ai_response})

        if record_id:
            update_analysis_only(record_id, json.dumps(messages, ensure_ascii=False))

        return jsonify({'status': 'success', 'messages': messages})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)})


@app.route('/api/history', methods=['GET'])
def list_history():
    records = get_all_history()
    return jsonify(records)


@app.route('/api/history/<int:rid>', methods=['DELETE'])
def delete_history(rid):
    delete_record_db(rid)
    return jsonify({'status': 'success'})


# ==========================================
# 前端模板
# ==========================================
HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>奇门遁甲 · 运筹帷幄</title>
    <link href="https://fonts.googleapis.com/css2?family=Ma+Shan+Zheng&family=Zhi+Mang+Xing&family=Noto+Serif+SC:wght@400;700;900&family=Long+Cang&display=swap" rel="stylesheet">
    <script src="https://cdn.jsdelivr.net/npm/marked/marked.min.js"></script>
    <script>{{ marked_js | safe }}</script>
    <style>
        :root {
            --bg-paper: #f7f4ed;
            --ink-primary: #1a1a1a;
            --ink-secondary: #5a5a5a;
            --cinnabar: #b83b3b;
            --cinnabar-dark: #8a2a2a;
            --gold: #bfa36f;
            --gold-dark: #8f7645;
            --border-color: #dcd6c8;
            --shadow-soft: 0 10px 40px rgba(0,0,0,0.08);
            --shadow-sharp: 0 2px 8px rgba(0,0,0,0.1);
        }

        * { box-sizing: border-box; }

        body {
            font-family: 'Noto Serif SC', serif;
            background-color: var(--bg-paper);
            background-image: url("data:image/svg+xml,%3Csvg viewBox='0 0 200 200' xmlns='http://www.w3.org/2000/svg'%3E%3Cfilter id='noiseFilter'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.65' numOctaves='3' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23noiseFilter)' opacity='0.05'/%3E%3C/svg%3E");
            color: var(--ink-primary);
            margin: 0;
            padding: 20px;
            display: flex;
            flex-direction: column;
            align-items: center;
            min-height: 100vh;
        }

        header {
            text-align: center;
            margin-bottom: 25px;
            position: relative;
        }

        h1 {
            font-family: 'Ma Shan Zheng', cursive;
            font-size: 4rem;
            margin: 0;
            color: var(--ink-primary);
            text-shadow: 3px 3px 0px rgba(184, 59, 59, 0.1);
            letter-spacing: 8px;
        }

        .subtitle {
            font-family: 'Long Cang', cursive;
            color: var(--cinnabar);
            font-size: 1.8rem;
            margin-top: -10px;
            opacity: 0.9;
        }

        .control-panel {
            background: rgba(255, 255, 255, 0.85);
            backdrop-filter: blur(8px);
            padding: 20px 30px;
            border-radius: 12px;
            box-shadow: var(--shadow-soft);
            margin-bottom: 30px;
            border: 1px solid rgba(255,255,255,0.6);
            max-width: 850px;
            width: 100%;
        }

        .form-grid {
            display: flex;
            flex-wrap: wrap;
            gap: 15px;
            justify-content: center;
            align-items: flex-end;
        }

        .input-group { display: flex; flex-direction: column; align-items: center; }
        .input-group label { font-size: 0.9rem; color: var(--ink-secondary); margin-bottom: 4px; font-family: 'Noto Serif SC', serif; }

        input {
            border: none; border-bottom: 2px solid var(--border-color); background: transparent;
            font-family: 'Noto Serif SC', serif; font-size: 1.3rem; font-weight: 700;
            color: var(--ink-primary); text-align: center; width: 65px; padding: 4px 0; transition: all 0.3s;
        }
        input:focus { outline: none; border-bottom-color: var(--cinnabar); }
        input[name="lon"] { width: 90px; }

        button {
            background: var(--cinnabar); color: #fff; border: none; padding: 8px 35px;
            border-radius: 4px; font-family: 'Noto Serif SC', serif; font-size: 1.1rem;
            font-weight: bold; cursor: pointer; box-shadow: 0 4px 12px rgba(184, 59, 59, 0.25);
            transition: all 0.3s; margin-left: 15px; margin-bottom: 2px;
        }
        button:hover { background: var(--cinnabar-dark); transform: translateY(-1px); }

        .result-container { width: 100%; max-width: 700px; animation: slideUp 0.8s cubic-bezier(0.16, 1, 0.3, 1); }

        .info-card {
            background: #fff; padding: 15px 25px; border-radius: 8px; box-shadow: var(--shadow-sharp);
            margin-bottom: 20px; border-top: 4px solid var(--cinnabar); display: grid;
            grid-template-columns: repeat(4, 1fr); gap: 15px; text-align: center;
        }
        .info-item { display: flex; flex-direction: column; }
        .info-label { font-size: 0.85rem; color: #999; margin-bottom: 4px;}
        .info-value { font-size: 1.1rem; font-weight: bold; color: var(--ink-primary); }
        .highlight-row {
            grid-column: span 4; margin-top: 10px; padding-top: 10px; border-top: 1px dashed #eee;
            color: var(--cinnabar); font-weight: 900; font-size: 1.25rem; font-family: 'Noto Serif SC';
        }

        .qimen-grid {
            display: grid; grid-template-columns: repeat(3, 1fr); aspect-ratio: 1/1; gap: 6px;
            padding: 6px; background: #2b2b2b; border: 4px solid #2b2b2b;
            box-shadow: var(--shadow-soft); border-radius: 2px;
        }
        .palace { background-color: #fff; position: relative; display: flex; flex-direction: column; justify-content: space-between; padding: 8px 10px; overflow: hidden; }
        .center-palace { background-color: #f0eadd; }
        .palace-bg {
            position: absolute; top: 50%; left: 50%; transform: translate(-50%, -50%);
            font-family: 'Ma Shan Zheng'; font-size: 8rem; color: rgba(0,0,0,0.06); pointer-events: none; z-index: 0; line-height: 1;
        }
        .element-group { position: relative; z-index: 1; height: 100%; display: flex; flex-direction: column; justify-content: space-between; }
        .top-row { display: flex; justify-content: space-between; align-items: flex-start; }
        .bottom-row { display: flex; justify-content: space-between; align-items: flex-end; }
        .god { font-family: 'Noto Serif SC', serif; font-size: 1.3rem; color: var(--cinnabar); font-weight: 900; writing-mode: vertical-rl; text-orientation: upright; letter-spacing: 2px; text-shadow: 1px 1px 0 rgba(255,255,255,0.8); }
        .stems { display: flex; flex-direction: column; align-items: center; font-family: 'Ma Shan Zheng', cursive; line-height: 0.9; margin-right: -2px; }
        .tian-stem { font-size: 2.8rem; color: var(--ink-primary); margin-bottom: -5px; z-index: 2; }
        .di-stem { font-size: 1.8rem; color: #777; font-weight: bold; z-index: 1; }
        .star { font-family: 'Noto Serif SC', serif; font-weight: 700; color: var(--ink-secondary); font-size: 1.3rem; }
        .door { font-family: 'Zhi Mang Xing', cursive; color: var(--gold-dark); font-size: 2rem; line-height: 1; text-shadow: 0 1px 0 rgba(255,255,255,1); }

        .ai-section { margin-top: 30px; width: 100%; max-width: 700px; background: #fff; border-radius: 12px; box-shadow: var(--shadow-soft); overflow: hidden; border: 1px solid rgba(184, 59, 59, 0.1); }
        .ai-header { background: linear-gradient(135deg, var(--cinnabar), var(--cinnabar-dark)); color: #fff; padding: 15px 20px; font-weight: bold; font-size: 1.2rem; }
        .ai-body { padding: 20px; }
        textarea {
            width: 100%; height: 80px; padding: 10px; border: 2px solid var(--border-color); border-radius: 8px;
            font-family: inherit; font-size: 1rem; resize: none; margin-bottom: 15px; transition: 0.3s; background: #fdfdfd;
        }
        textarea:focus { border-color: var(--cinnabar); outline: none; background: #fff; }
        .ai-btn { width: 100%; background: var(--ink-primary); color: #fff; padding: 12px; border-radius: 8px; font-size: 1.1rem; border: none; cursor: pointer; }
        .ai-btn:disabled { background: #ccc; }
        .ai-result { margin-top: 20px; padding-top: 20px; border-top: 1px solid #eee; display: none; text-align: left; line-height: 1.8; font-size: 1rem; }

        /* 新增：聊天追问UI */
        .chat-history {
            max-height: 50vh; overflow-y: auto; padding: 15px; background: rgba(247, 244, 237, 0.4);
            border: 1px solid #eee; border-radius: 8px; margin-bottom: 15px; display: flex; flex-direction: column; gap: 15px;
        }
        .msg-user { text-align: right; }
        .msg-user-content {
            display: inline-block; background: var(--cinnabar); color: white; padding: 10px 15px;
            border-radius: 12px 12px 0 12px; text-align: left; max-width: 85%; font-size: 0.95rem;
        }
        .msg-ai { text-align: left; }
        .msg-ai-content {
            display: inline-block; background: white; color: var(--ink-primary); padding: 15px;
            border-radius: 12px 12px 12px 0; border: 1px solid var(--border-color);
            box-shadow: 0 2px 5px rgba(0,0,0,0.05); max-width: 95%; line-height: 1.7;
        }
        .msg-ai-content p { margin-top: 0; }
        .chat-input-group { display: flex; gap: 10px; }
        .chat-input-group textarea { height: 50px; margin-bottom: 0; flex-grow: 1; }
        .chat-input-group .ai-btn { width: auto; white-space: nowrap; padding: 0 25px; }


        /* 更新：修复 X 按钮不居中的问题 */
        .history-btn {
            position: fixed; top: 20px; right: 20px; background: var(--ink-primary); color: white;
            border-radius: 50%; width: 45px; height: 45px; display: flex; align-items: center; justify-content: center;
            cursor: pointer; z-index: 101; box-shadow: 0 4px 10px rgba(0,0,0,0.2);
            font-size: 1.5rem; transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
            /* 下面三行是关键新增 */
            font-family: system-ui, -apple-system, sans-serif; 
            line-height: 1;
            padding: 0;
        }
        .history-btn:hover { background: var(--cinnabar); transform: scale(1.05); }

        .drawer {
            position: fixed; top: 0; right: -320px; width: 300px; height: 100%; background: white;
            box-shadow: -5px 0 20px rgba(0,0,0,0.1); transition: 0.3s cubic-bezier(0.4, 0, 0.2, 1);
            z-index: 100; padding: 20px; padding-top: 80px; /* 留出顶部按钮的空间 */ overflow-y: auto;
        }
        .drawer.open { right: 0; }

        .drawer-header {
            font-weight: bold; font-size: 1.2rem; margin-bottom: 20px;
            border-bottom: 2px solid var(--cinnabar); padding-bottom: 10px;
        }
        .history-item { border-bottom: 1px solid #eee; padding: 12px 0; display: flex; justify-content: space-between; align-items: flex-start; }
        .history-info { cursor: pointer; flex-grow: 1; }
        .history-summary { font-weight: bold; font-size: 0.95rem; color: var(--ink-primary); }
        .history-time { font-size: 0.8rem; color: #999; margin-top: 4px; }
        .history-q { font-size: 0.85rem; color: var(--cinnabar); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; max-width: 180px; margin-top: 4px; }
        .del-btn { color: #ccc; cursor: pointer; padding: 0 0 0 10px; font-size: 1.2rem; }
        .del-btn:hover { color: var(--cinnabar); }
        .overlay { position: fixed; top: 0; left: 0; width: 100%; height: 100%; background: rgba(0,0,0,0.3); z-index: 98; display: none; backdrop-filter: blur(2px); }
        .overlay.show { display: block; }
        .error-box { background: #ffebee; color: #c62828; padding: 15px; border-radius: 8px; text-align: center; }

        @keyframes slideUp { from { opacity: 0; transform: translateY(20px); } to { opacity: 1; transform: translateY(0); } }
        @media (max-width: 600px) {
            h1 { font-size: 2.8rem; }
            .control-panel { padding: 15px; } .info-card { grid-template-columns: repeat(2, 1fr); }
            .highlight-row { grid-column: span 2; }
            .qimen-grid { gap: 3px; padding: 3px; border-width: 3px; } .palace { padding: 4px 6px; }
            .god { font-size: 1rem; } .tian-stem { font-size: 2rem; } .di-stem { font-size: 1.2rem; }
            .door { font-size: 1.5rem; } .star { font-size: 1rem; } .palace-bg { font-size: 5rem; }
            .chat-input-group { flex-direction: column; } .chat-input-group .ai-btn { width: 100%; }
        }
    </style>
</head>
<body>
    <div class="history-btn" id="historyBtn" onclick="toggleHistory()">📜</div>
    <div class="overlay" onclick="toggleHistory()"></div>

    <div class="drawer" id="historyDrawer">
        <div class="drawer-header">历史记录</div>
        <div id="historyList">加载中...</div>
    </div>

    <header>
        <h1>奇门遁甲</h1>
        <div class="subtitle">运筹帷幄 · 决胜千里</div>
    </header>

    <form class="control-panel" method="POST" action="/">
        <div class="form-grid">
            <div class="input-group"><label>年</label><input type="number" name="year" value="{{ v.year }}"></div>
            <div class="input-group"><label>月</label><input type="number" name="month" value="{{ v.month }}"></div>
            <div class="input-group"><label>日</label><input type="number" name="day" value="{{ v.day }}"></div>
            <div class="input-group"><label>时</label><input type="number" name="hour" value="{{ v.hour }}"></div>
            <div class="input-group"><label>分</label><input type="number" name="minute" value="{{ v.minute }}"></div>
            <div class="input-group"><label>经度</label><input type="number" step="0.01" name="lon" value="{{ v.lon }}"></div>
            <button type="submit">起局排盘</button>
        </div>
        <div style="text-align:center; margin-top:12px; font-size:0.85rem; color:#999; cursor:pointer; font-weight:bold;" onclick="getLocation()">
            📍 点击获取当前位置与时间
        </div>
    </form>

    {{ result|safe }}

    {% if result %}
    <div class="ai-section result-container">
        <div class="ai-header">🔮 大师解盘与推演</div>
        <div class="ai-body">
            <input type="hidden" id="recordId" value="{{ record_id }}">

            <div id="initialForm">
                <textarea id="question" placeholder="请输入您想问的具体事项，例如：“面试能否顺利通过？”">{{ h_q }}</textarea>
                <button class="ai-btn" onclick="askAI()" id="aiBtn">开始起卦解盘</button>
            </div>

            <div id="loading" style="display:none; text-align:center; margin:15px 0; color:#555;">✨ 正在连接天机，请稍候...</div>

            <div id="chatArea" style="display:none;">
                <div id="chatHistory" class="chat-history"></div>
                <div class="chat-input-group">
                    <textarea id="followUpQuestion" placeholder="你可以继续询问盘内细节，例如：感情走势如何？"></textarea>
                    <button class="ai-btn" id="followUpBtn" onclick="sendFollowUp()">追问</button>
                </div>
            </div>

            <div class="ai-result" id="aiResult"></div>
        </div>
    </div>
    {% endif %}

    <script>
        // 初始化保存对话的全局变量
        window.chatMessages = [];

        window.onload = function() {
            // 解析历史解盘数据
            const historyAnalysis = {{ h_a | tojson | safe }};
            if (historyAnalysis) {
                try {
                    // 如果是最新的多轮聊天格式 (JSON 数组)
                    const parsed = JSON.parse(historyAnalysis);
                    if (Array.isArray(parsed)) {
                        window.chatMessages = parsed;
                        document.getElementById('initialForm').style.display = 'none';
                        document.getElementById('chatArea').style.display = 'block';
                        renderChatHistory();
                    } else { throw new Error("Not Array"); }
                } catch(e) {
                    // 兼容旧版本的纯文本格式
                    document.getElementById('aiResult').innerHTML = marked.parse(historyAnalysis);
                    document.getElementById('aiResult').style.display = 'block';
                }
            }
        }

        function extractQuestion(content) {
            // 从内置的 system prompt 里提取用户的问题
            const match = content.match(/【用户问题】:\\n"([^"]+)"/);
            return match ? match[1] : "起局解盘";
        }

        // 渲染对话界面
        function renderChatHistory() {
            const chatBox = document.getElementById('chatHistory');
            chatBox.innerHTML = '';
            // 忽略索引为0的 System Prompt
            for(let i = 1; i < window.chatMessages.length; i++) {
                const msg = window.chatMessages[i];
                const div = document.createElement('div');

                if (msg.role === 'user') {
                    div.className = 'msg-user';
                    // 第一次的用户输入包含了繁重的排盘 JSON，我们需要提取纯粹的问题展示
                    let displayString = i === 1 ? extractQuestion(msg.content) : msg.content;
                    div.innerHTML = `<div class="msg-user-content"><strong>🙋‍♂️:</strong> ${displayString}</div>`;
                } else if (msg.role === 'assistant') {
                    div.className = 'msg-ai';
                    div.innerHTML = `<div class="msg-ai-content">${marked.parse(msg.content)}</div>`;
                }
                chatBox.appendChild(div);
            }
            chatBox.scrollTop = chatBox.scrollHeight;
        }

        function getLocation() {
            if (navigator.geolocation) { navigator.geolocation.getCurrentPosition(pos => {
                document.querySelector('input[name="lon"]').value = pos.coords.longitude.toFixed(2);
                const now = new Date();
                document.querySelector('input[name="year"]').value = now.getFullYear();
                document.querySelector('input[name="month"]').value = now.getMonth() + 1;
                document.querySelector('input[name="day"]').value = now.getDate();
                document.querySelector('input[name="hour"]').value = now.getHours();
                document.querySelector('input[name="minute"]').value = now.getMinutes();
            }); } else { alert("浏览器不支持地理定位。"); }
        }

        // 第一次发起解析
        async function askAI() {
            const question = document.getElementById('question').value;
            const recordId = document.getElementById('recordId').value;
            if (!question.trim()) { alert("请输入问题"); return; }

            const btn = document.getElementById('aiBtn');
            const loading = document.getElementById('loading');

            btn.disabled = true; btn.innerText = "分析中...";
            loading.style.display = 'block';

            const payload = {
                year: document.querySelector('input[name="year"]').value,
                month: document.querySelector('input[name="month"]').value,
                day: document.querySelector('input[name="day"]').value,
                hour: document.querySelector('input[name="hour"]').value,
                minute: document.querySelector('input[name="minute"]').value,
                lon: document.querySelector('input[name="lon"]').value,
                question: question,
                record_id: recordId
            };

            try {
                const response = await fetch('/analyze', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(payload)
                });
                const data = await response.json();
                if (data.status === 'success') {
                    window.chatMessages = data.messages;
                    document.getElementById('initialForm').style.display = 'none';
                    document.getElementById('chatArea').style.display = 'block';
                    renderChatHistory();
                } else {
                    alert("错误: " + data.message);
                }
            } catch (e) {
                alert("网络错误: " + e);
            } finally {
                btn.disabled = false; btn.innerText = "重新分析";
                loading.style.display = 'none';
                loadHistoryList();
            }
        }

        // 多轮追问
        async function sendFollowUp() {
            const inputField = document.getElementById('followUpQuestion');
            const questionText = inputField.value;
            const recordId = document.getElementById('recordId').value;
            if (!questionText.trim()) return;

            // 提前将用户问题展现在界面上
            window.chatMessages.push({ role: 'user', content: questionText });
            renderChatHistory();
            inputField.value = '';

            const btn = document.getElementById('followUpBtn');
            const loading = document.getElementById('loading');

            btn.disabled = true;
            loading.style.display = 'block';

            try {
                const response = await fetch('/chat', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        messages: window.chatMessages.slice(0, -1), // 把刚才暂存的问题切掉，作为新参数传入
                        question: questionText,
                        record_id: recordId
                    })
                });
                const data = await response.json();
                if (data.status === 'success') {
                    window.chatMessages = data.messages; // 更新完整的聊天历史
                    renderChatHistory();
                } else {
                    alert("追问出错: " + data.message);
                    window.chatMessages.pop(); // 回滚消息
                    renderChatHistory();
                }
            } catch (e) {
                alert("网络连接错误");
                window.chatMessages.pop();
                renderChatHistory();
            } finally {
                btn.disabled = false;
                loading.style.display = 'none';
            }
        }

        // 历史侧边栏 & 按钮动画交互
        function toggleHistory() {
            const drawer = document.getElementById('historyDrawer');
            const overlay = document.querySelector('.overlay');
            const btn = document.getElementById('historyBtn');

            if (drawer.classList.contains('open')) {
                // 收起状态
                drawer.classList.remove('open');
                overlay.classList.remove('show');
                // 按钮变回 📜
                btn.innerHTML = '📜';
                btn.style.transform = 'rotate(0deg)';
                btn.style.background = 'var(--ink-primary)';
            } else {
                // 弹出状态
                drawer.classList.add('open');
                overlay.classList.add('show');
                loadHistoryList();
                // 按钮转圈变成 ✕
                btn.innerHTML = '✕';
                btn.style.transform = 'rotate(180deg)';
                btn.style.background = 'var(--cinnabar)';
            }
        }

        async function loadHistoryList() {
            const listDiv = document.getElementById('historyList');
            try {
                const res = await fetch('/api/history');
                const data = await res.json();
                if (data.length === 0) {
                    listDiv.innerHTML = '<div style="text-align:center;color:#999;margin-top:20px">暂无记录</div>';
                    return;
                }
                let html = '';
                data.forEach(item => {
                    const qText = item.question ? `<div>问: ${item.question}</div>` : '';
                    html += `
                    <div class="history-item">
                        <div class="history-info" onclick="window.location.href='/?history_id=${item.id}'">
                            <div class="history-summary">${item.summary}</div>
                            <div class="history-time">${item.timestamp.slice(5,16)}</div>
                            <div class="history-q">${qText}</div>
                        </div>
                        <div class="del-btn" onclick="deleteHistory(${item.id})">×</div>
                    </div>`;
                });
                listDiv.innerHTML = html;
            } catch (e) {
                listDiv.innerHTML = '加载失败';
            }
        }

        async function deleteHistory(id) {
            if (!confirm('确定删除这条记录吗？')) return;
            await fetch(`/api/history/${id}`, { method: 'DELETE' });
            loadHistoryList();
        }
    </script>
</body>
</html>
"""

if __name__ == '__main__':
    print("启动奇门遁甲 Web 服务...")
    app.run(host='0.0.0.0', port=5000, debug=True)