#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Copyright © https://reddit.com/u/buhoho
#
# require macOS
# require sox (sound of exchange command)
#
# fadoshtui is macOS say command front ui.
# say コマンドで作成した音声をsoxを使って速度変更などの調整しながら再生する

import os, os.path, time, sys, importlib
import shutil, threading
import locale, unicodedata
import re, pickle, argparse, csv, tempfile
import fcntl

from curses import *
from hashlib import md5
from subprocess import call, Popen, STDOUT, PIPE
from copy import copy

importlib.reload(sys)
# sys.setdefaultencoding("UTF-8") # 暫定的

locale.setlocale(locale.LC_ALL, '')
CODE    = locale.getpreferredencoding()
CONF    = os.environ['HOME'] + '/.config/fadosh'
try:
    from subprocess import DEVNULL
except ImportError:
    DEVNULL = open(os.devnull, 'wb')
try:
    call(['play', '--help'], stdout=DEVNULL, stderr=STDOUT)
except:
    sys.stderr.write("Error: not have play command(sox player) this enviroment\n.")
    exit(1)

COLOR_PRIMARY    = 105
COLOR_PRIMARY2   = 106
COLOR_SECONDARY  = 107
COLOR_DEFAULT    = 100
COLOR_DEFAULT_HI = 101
COLOR_SERIF1     = 110
COLOR_SERIF1_HI  = 111
COLOR_SERIF2     = 112
COLOR_SERIF2_HI  = 113
COLOR_KAKKO1     = 114
COLOR_KAKKO1_HI  = 115


def createConfig():
    if not os.path.isdir(os.environ['HOME'] + '/.config'):
        os.mkdir(os.environ['HOME'] + '/.config')
    if not os.path.isdir(CONF):
        os.mkdir(CONF)

#ファイルをロードする。コールバック無いと動かない
#ない場合、ロード失敗でFalseを返す
def loadAbs(filename, flg, func):
    count = 4
    while count:
        try:
            with open(filename, flg) as f:
                 return func(f)
        except IOError as e:
            return False
        except ValueError as e:
            napms(50) # 並列アクセスでコケる時がある
            count -= 1

# 最後に読んでいた位置をファイルに保存する
class History():
    pkl = CONF + '/history.pkl'
    lock_file = CONF + '/history.lock'

    def __init__(self, hash, length):
        self.hash = hash
        self.last = None

    def get(self, ag):
        """ロック付きで履歴を読み込む"""
        try:
            with open(self.lock_file, 'a+') as lock:
                fcntl.flock(lock.fileno(), fcntl.LOCK_SH)
                try:
                    with open(self.pkl, 'rb') as f:
                        hist = pickle.load(f)
                    last = hist.get(self.hash, 0)
                except (IOError, EOFError, pickle.UnpicklingError):
                    last = 0
                finally:
                    fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
        except IOError:
            last = 0
        return ag.index - 1 if ag.index else last

    def set(self, idx):
        if self.last:
            self.last.cancel()
        self.last = threading.Timer(0.2, lambda: self._set(idx))
        self.last.start()

    def _set(self, idx):
        """ロック付きでアトミックに履歴を更新"""
        try:
            with open(self.lock_file, 'a+') as lock:
                fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
                try:
                    # 同じロック内で read → update → write
                    hist = {}
                    try:
                        with open(self.pkl, 'rb') as f:
                            hist = pickle.load(f)
                    except (IOError, EOFError, pickle.UnpicklingError):
                        pass

                    hist[self.hash] = idx

                    # 一時ファイル経由でアトミック書き込み
                    tmp_path = self.pkl + f'.tmp.{os.getpid()}'
                    with open(tmp_path, 'wb') as f:
                        pickle.dump(hist, f)
                    os.rename(tmp_path, self.pkl)
                finally:
                    fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
        except IOError:
            pass
        return idx

    def cancel_timer(self):
        """終了時にタイマーをキャンセル"""
        if self.last:
            self.last.cancel()

# TSVをロードして、その設定通りに読み上げ置換する
# 置換の適用はファイルの上から順番に行う
class ReplaceWord():
    def __init__(self):
        self.words = loadAbs(CONF + '/replace.tsv', 'r', (lambda f:
            [[re.compile(n), m]
                for (n, m) in csv.reader(f, delimiter='\t')])) or []
        # say をクラッシュさせる文字列
        self.words += [[re.compile("[ -]"), ""],
                       [re.compile("-+"), ""],
                       [re.compile("ー。"), "ー"],
                       [re.compile("ー([？?！!」])"), r"\1"]] 
    # 読み替え置換
    def replace(self, txt):
        for (ptn, replace) in self.words or []:
            txt = ptn.sub(replace, txt)
        return txt

def f2md5(filename):
    hasher = md5()
    with open(filename, 'rb') as f:
         hasher.update(f.read())
    return hasher.hexdigest()

def loadLines(filename):
    lines = []
    with open(filename, encoding="UTF-8") as f:
        for t in f:
            lines.append(t.strip("\n"))
    lines.append("")
    return lines

def play(filename):
    Popen(["play", CONF + '/' + filename], stdout=DEVNULL, stderr=STDOUT);

class Serif():
    def __init__(self, close, color, color_hi, pitch):
        self.close = close
        self.color = color
        self.color_hi = color_hi
        self.pitch = pitch
    def txt(self, txt):
        my = copy(self)
        my.txt = txt
        return my

class SerifParser():
    # かっこ開始文字、閉じ文字、カラーID、ピッチ
    kakko = {
            None : Serif(None,  COLOR_DEFAULT,COLOR_DEFAULT_HI, -140), 
            u'「': Serif(u'」', COLOR_SERIF1, COLOR_SERIF1_HI,   -30),
            u'『': Serif(u'』', COLOR_SERIF2, COLOR_SERIF2_HI,   40),
            u'【': Serif(u'】', COLOR_KAKKO1, COLOR_KAKKO1_HI,   40) 
            }

    def __init__(self):
        # デフォルト色、ピッチ。状態が残るとマズイのでコンストラクタで初期化
        self.stack = [self.kakko[None]]
    def parse(self, line):
        """ Serifのリスト """
        lines = []
        strStack = ''
        for c in line:
            strStack += c
            if self.stack[-1].close == c:
                lines += [self.stack[-1].txt(strStack)]
                self.stack.pop()
                strStack = ''
            if c in self.kakko.keys(): #開始かっこ
                strStack = strStack[:-1]
                if strStack != '':
                    lines += [self.stack[-1].txt(strStack)]
                strStack = c
                self.stack.append(self.kakko[c])
        if strStack:
            lines += [self.stack[-1].txt(strStack)]
        return lines


class AudioCacheManager:
    def __init__(self, output_dir, voice_opt, rw_instance):
        self.cache_dir = output_dir  # 既にインスタンス固有
        self.voice = voice_opt
        self.rw = rw_instance
        self._current_index = 0
        self._lines = []
        self.running = True

        # 排他制御用: { md5_hash: threading.Event }
        # 「今、誰かがこのハッシュを作っているか」を管理する
        self.processing_events = {}
        self.lock = threading.Lock()
        self.context_lock = threading.Lock()  # コンテキスト用ロック

        self.thread = threading.Thread(target=self._worker, daemon=True)
        self.thread.start()

    def set_context(self, index, lines):
        with self.context_lock:
            self._current_index = index
            self._lines = lines

    def _get_context(self):
        """スレッドセーフにコンテキストを取得"""
        with self.context_lock:
            return self._current_index, self._lines

    def get_audio_path_sync(self, text):
        """
        メインスレッド用インターフェース
        生成処理は内部で完結させ、競合時は待機させる
        """
        if not text: return None
        
        md5_hash = md5(text.encode('utf-8')).hexdigest()
        filepath = os.path.join(self.cache_dir, md5_hash + '.aiff') # format指定してもwavにすると動かない

        # 1. 既にファイルがある (Fast Path)
        if os.path.exists(filepath):
            return filepath

        # 2. 無い場合、作成権限を確認 (排他制御)
        event = None
        owner = False

        with self.lock:
            if md5_hash in self.processing_events:
                # 誰かが作成中 -> 待機チケット(Event)を受け取る
                event = self.processing_events[md5_hash]
            else:
                # 誰も作っていない -> 自分が作成担当になる
                event = threading.Event()
                self.processing_events[md5_hash] = event
                owner = True

        if not owner:
            # 作成中なら、タイムアウト付きで完了を待つ
            if event.wait(timeout=10.0):
                if os.path.exists(filepath):
                    return filepath
            # タイムアウトまたはファイルなし → 再生成を試みる
            return self._fallback_generate(text, filepath)

        # 3. 自分が担当者の場合のみ、生成処理を実行
        try:
            self._generate_file(text, filepath)
        finally:
            # 完了通知
            event.set()
            # 登録解除
            with self.lock:
                if md5_hash in self.processing_events:
                    del self.processing_events[md5_hash]

        return filepath

    def _fallback_generate(self, text, filepath):
        """タイムアウト時のフォールバック生成（例外を安全に処理）"""
        if os.path.exists(filepath):
            return filepath
        try:
            self._generate_file(text, filepath)
            return filepath if os.path.exists(filepath) else None
        except Exception:
            # 生成失敗時は None を返す（呼び出し元で処理）
            return None

    def _generate_file(self, text, filepath):
        """ ファイル生成の実体（Manager内部でのみ使用） """
        part_path = filepath + '.part' 
        speak_text = self.rw.replace(text)
        
        cmd = ['say', speak_text, '-o', part_path]
        if self.voice:
            cmd += ['-v', self.voice]
            
        ret = call(cmd, stdout=DEVNULL, stderr=STDOUT)
        
        if ret == 0:
            os.rename(part_path, filepath)
        else:
            if os.path.exists(part_path): os.remove(part_path)

    def _worker(self):
        """ バックグラウンド先読みスレッド """
        LOOK_BACK = 5
        LOOK_AHEAD = 5

        while self.running:
            # スレッドセーフにコンテキストを取得
            curr, lines = self._get_context()

            if not lines:
                time.sleep(0.5)
                continue

            start_idx = max(0, curr - LOOK_BACK)
            end_idx = min(len(lines), curr + LOOK_AHEAD)
            
            from fadoshtui import SerifParser 
            parser = SerifParser()

            for idx in range(start_idx, end_idx):
                if not self.running:
                    break
                if idx >= len(lines):
                    break

                line = lines[idx]
                if not isinstance(line, str):
                    continue

                serif_list = parser.parse(line)
                
                # ★修正: idx > curr を idx >= curr に変更
                # これで「現在行」も生成対象になり、再生中の行の「次のパーツ」が裏で作られます
                if idx >= curr:
                    for serif in serif_list:
                        md5_hash = md5(serif.txt.encode('utf-8')).hexdigest()
                        filepath = os.path.join(self.cache_dir, md5_hash + '.aiff')
                        
                        # ファイルがなく、かつ作成中でもない時だけ予約を入れる
                        should_generate = False
                        with self.lock:
                            if not os.path.exists(filepath) and md5_hash not in self.processing_events:
                                self.processing_events[md5_hash] = threading.Event()
                                should_generate = True
                        
                        if should_generate:
                            try:
                                self._generate_file(serif.txt, filepath)
                            finally:
                                with self.lock:
                                    if md5_hash in self.processing_events:
                                        self.processing_events[md5_hash].set()
                                        del self.processing_events[md5_hash]
            
            time.sleep(0.1)

    def cleanup(self):
        self.running = False
        self.thread.join(timeout=2.0)  # ワーカーの終了を待つ
        try:
            if os.path.exists(self.cache_dir):
                shutil.rmtree(self.cache_dir)
        except OSError:
            pass




# 改行して配列で返す
# 一文字づつ文字幅を確認する必要がある。(他にやり方無いのか。。。エグい)
def getMultiLine(srcLine, w):
    if srcLine == None:
        return []
    if (w % 2 != 0):
        w -= 1 # 全角文字を考慮して偶数列に丸めて画面の幅に余裕をもたせる
    lines = []
    oneLine = ""
    n = 0
    # ユニコードにしないとバイトずつの操作になる。。
    for c in srcLine:
        n += min(2, len(c.encode(CODE)))
        if n < w:
            oneLine += c
            continue
        # つまり行端に到達した or 一文が終了した
        lines.append(oneLine + c)
        oneLine = ""
        n = 0
    lines.append(oneLine)
    return lines

def saycommand(self, tx, pitch):
    # マネージャーから音声ファイルのパスを取得（無ければ同期生成される）
    audio_file = self.cache_mgr.get_audio_path_sync(tx)
    if audio_file is None or not os.path.exists(audio_file):
        return None
    cmd = ['play', '-q', audio_file, 'tempo', '-s', str(self.opt.rate), 'pitch', str(pitch)]
    try:
        return Popen(cmd, stdout=DEVNULL, stderr=STDOUT)
    except (FileNotFoundError, OSError):
        return None

class FadoshTUI():
    def __init__(self, opt):
        self.st = '■'
        self.lines = loadLines(opt.file)
        self.hist  = History(f2md5(opt.file), len(self.lines))
        self.opt   = opt
        self.rw = ReplaceWord()
        # ★ キャッシュマネージャーの初期化（インスタンス固有ディレクトリ）
        cache_root = os.path.join(tempfile.gettempdir(), 'fadosh_catch')
        os.makedirs(cache_root, exist_ok=True)
        self._cleanup_old_caches(cache_root, max_age_hours=1)
        # インスタンス固有のキャッシュディレクトリ（PID + タイムスタンプ）
        cache_base = os.path.join(cache_root, f'{os.getpid()}_{int(time.time())}')
        os.makedirs(cache_base, exist_ok=True)
        self.cache_mgr = AudioCacheManager(cache_base, self.opt.voice, self.rw)
        # 初期コンテキストセット
        self.cache_mgr.set_context(self.hist.get(self.opt), self.lines)

    def _cleanup_old_caches(self, cache_root, max_age_hours=1):
        """起動時に古いキャッシュディレクトリを掃除"""
        now = time.time()
        max_age_sec = max_age_hours * 3600
        try:
            for entry in os.listdir(cache_root):
                path = os.path.join(cache_root, entry)
                if os.path.isdir(path):
                    try:
                        mtime = os.path.getmtime(path)
                        if now - mtime > max_age_sec:
                            shutil.rmtree(path, ignore_errors=True)
                    except OSError:
                        pass
        except OSError:
            pass

    def cursesInit(self):
        use_default_colors()
        init_pair(0, -1, -1)
        for i in range(16):
            init_pair(i, i, -1)
        init_pair(COLOR_PRIMARY, 236, 33)
        init_pair(COLOR_PRIMARY2,   33, -1)
        init_pair(COLOR_SECONDARY,  235, 248)
        init_pair(COLOR_DEFAULT,    -1, -1)
        init_pair(COLOR_DEFAULT_HI, -1, 237)
        init_pair(COLOR_SERIF1,     39, -1)
        init_pair(COLOR_SERIF1_HI,  39, 236)
        init_pair(COLOR_SERIF2,     123, -1)
        init_pair(COLOR_SERIF2_HI,  123, 236)
        init_pair(COLOR_KAKKO1,     5, -1)
        init_pair(COLOR_KAKKO1_HI,  5, 236)
        # init_pair(120, 198, -1)
        curs_set(False) #カーソル非表示

    def getCmd(self):
        h, w = self.yx()
        self.scr.addstr(h-1, 0, ' ' * (w - 1))
        self.scr.addstr(h-1, 0, ':')

        self.scr.nodelay(False)
        curs_set(True) #カーソル表示
        echo()

        s = self.scr.getstr(h-1, 1)

        noecho()
        curs_set(False) #カーソル非表示
        #self.scr.nodelay(True)
        return s

    def debugPrint(self, s):
        self.scr.addstr(0, 0, str(s), color_pair(1) | A_REVERSE)
        self.scr.nodelay(False)
        self.scr.getkey()

    def sayWaitLoop(self):
        """
        読み上げとその間の処理を停止するループ。一部のキー入力を受け付ける
        読み上げ継続ならTrue、停止ならFalseを返す
        """
        for se in self.playSerifParse():
            proc = saycommand(self, se.txt, se.pitch)
            while (proc and proc.poll() == None):

                op = self.scr.getch()
                try:
                    c = chr(op)
                except:
                    c = None

                if c == 'h' or op == KEY_LEFT:
                    self.rate(-0.1)
                if c == 'l' or op == KEY_RIGHT:
                    self.rate(+0.1)
                if op == KEY_RESIZE:
                    self.scr.clear()
                    self.scr.refresh()
                    self.render()
                if c and c in "[] q\n":
                    if proc is not None and proc.poll() is None:
                        try:
                            proc.kill()
                            proc.wait(timeout=1.0)  # ゾンビプロセス防止
                        except (ProcessLookupError, OSError):
                            pass
                    if c == '[':
                        i = self.index - 1
                        # 境界チェック追加
                        while i >= 0 and self.lines[i].strip() == "":
                            i -= 1
                        if i >= 0:
                            self.jumpidx(i - 1)
                        return True
                    if c == ']':
                        return True # 再生は続けたまま現在の読み上げキャンセル
                    if c and c in " q\n": # 終了
                        return False

                self.stLineRender()
                napms(40)

        return True

    def playLoop(self):
        """ 読み上げが終わったら次の行を読む。そんなループ """
        self.st = '▶'
        self.scr.nodelay(True)
        while self.index < len(self.lines) and\
              type(self.lines[self.index]) == str:

            self.hist.set(self.index)
            self.render()

            napms(60)

            if not self.sayWaitLoop():
                break
            if self.index >= len(self.lines) -1:
                break
            self.moveidx(+1)
        self.scr.nodelay(False)
        play('close.wav')
        self.st = '■'

    def wcharOffsetTrim(self, text, offset):
        real = 0
        wbreak = True
        for c in text:
            real += min(2, len(c.encode(CODE)))
            if real == offset:
                wbreak = False
            if real > offset:
                return max(0, offset + ( -1 if wbreak else 0))
        return offset

    def render(self):
        self.stLineRender()
        self._render()

    def stLineRender(self):
        """
        ステータスラインを描画する
        """
        status = (" {} {:>5} / {:<5} ({:1.2}x) ".format(
                    self.st,
                    self.index + 1,
                    len(self.lines),
                    self.opt.rate) +
                    # ToDo:ファイル名に/が入っていることを考慮していない
                    re.split(r"/", self.opt.file)[-1]
                )

        h, w = self.yx()
        try:
            self.stline.resize(1, w)
            self.stline.addstr(0, 0, ' ' * w)
            self.scr.addstr(h-1, 0, ' ' * w) # cmdline(scr)をrefresh
        except:
            w = self.stline.getmaxyx()[1];

        self.stline.mvwin(h-2, 0)
        status = getMultiLine(status, w-2)[0]
        self.stline.addstr(0, 0, status)
        # プログレスバー作成
        ratio = float(self.index) / len(self.lines)
        ratio = (self.index + (ratio * h)) / len(self.lines)# 画面の高さ考慮
        # プログレスバー。比率を画面幅にマッピング
        offset = self.wcharOffsetTrim(status, min(int(w * ratio), w))
        self.stline.chgat(0, 0, offset, color_pair(COLOR_PRIMARY))
        self.stline.refresh()

    def playSerifParse(self):
        """
        カレント行の手前の文章もパースして読み上げ位置のセリフ状態を正確に
        判定する。改行されたセリフを想定した処理
        """
        sPerser = SerifParser()
        before = 5
        se = []
        start_idx = max(0, self.index - before)
        end_idx = min(len(self.lines), self.index + 1)
        for idx in range(start_idx, end_idx):
            if isinstance(self.lines[idx], str):
                se = sPerser.parse(self.lines[idx])
        return se if se else []

    def refreshBuf(self, ly, lx):
        """
        描画バッファを更新
        """
        shift = max(0, min(ly/2, self.opt.context)) # 行が画面内に入るように
        renderBuf = []
        before = 8 
        sPerser = SerifParser();
        currIdx = 0

        for y in range((shift + before) * -1, ly):
            idx = self.index + y
            # テキスト範囲外ならチルダ
            tx = self.lines[idx] if idx >= 0 and idx < len(self.lines) else "~"

            current_color = A_BOLD if self.index == idx else 0

            for txt in getMultiLine(tx, lx -1):
                se = sPerser.parse(txt)
                #+=だとタプルが展開されて配列要素にダイレクト挿入される
                renderBuf.append((se, current_color))
                if currIdx == 0 and current_color:
                    currIdx = len(renderBuf) - 1

        return renderBuf[currIdx - shift:]

    def _render(self):
        """
        スクリーンに描画する
        """
        h, w = self.yx()
        ly, lx = (h - 1, w - 2)

        try:
            self.lline.resize(ly, lx)
            self.scr.addstr(h-1, 0, ' ' * w) # cmdline(scr)をrefresh
        except:
            ly, lx = self.lline.getmaxyx();

        buf = self.refreshBuf(ly, lx)

        # 表示用の一行を描画する
        for y in range(ly - 1):
            se, current = buf[y]
            # 行全体を背景色でクリア（scrに対して行うのでパディング部分も塗れる）
            try:
                self.scr.addstr(y, 0, ' ' * w, color_pair(COLOR_DEFAULT))
            except curses.error:
                pass # 画面端のリサイズ直後などで死なないように
            self.lline.move(y, 0)

            for seri in se:
                if current:
                    # self.scr.addstr(y, 0, ' ' * w, color_pair(seri.color_hi))
                    self.lline.addstr(seri.txt, color_pair(seri.color_hi) | current)
                else:
                    self.lline.addstr(seri.txt, color_pair(seri.color))

        self.lline.refresh()

    # テキストの範囲に収まるようindexを相対移動
    def moveidx(self, n):
        self.index = max(0, min(len(self.lines) - 1, self.index + n))
        # ★ Workerに現在地を通知
        self.cache_mgr.set_context(self.index, self.lines)

    # 範囲を考慮して、n行に絶対移動
    def jumpidx(self, n):
        self.index = 0
        self.moveidx(n)

    def yx(self):
        return self.scr.getmaxyx()

    def rate(self, rate):
        self.opt.rate = max(0.1, min(9.0, self.opt.rate + rate))

    def mainLoop(self):
        self.hist.set(self.index)
        op = self.scr.getch()

        try:
            c = chr(op)
        except:
            c = None

        if c == ':':
            c = self.getCmd()
            if c.isdigit():
                self.jumpidx(int(c) -1)
            elif len(c) == 1:
                c = c

        if c == 'k'   or op == KEY_UP:    self.moveidx(-1)
        elif c == 'j' or op == KEY_DOWN:  self.moveidx(+1)
        elif c == 'K' or op == KEY_PPAGE: self.moveidx(-self.yx()[0]-1)
        elif c == 'J' or op == KEY_NPAGE: self.moveidx(+self.yx()[0]-1)
        elif c == 'h' or op == KEY_LEFT:  self.rate(-0.1)
        elif c == 'l' or op == KEY_RIGHT: self.rate(+0.1)
        elif op == KEY_RESIZE:
            self.scr.clear()
            self.scr.refresh()
        elif c == 'q':
            return False

        self.render()

        if c and c in " \n":
            self.playLoop();
            self.stLineRender()

        if self.opt.auto and self.index ==len(self.lines) -1:
            return False

        return True #ループ継続

    def main(self, screen):
        self.cursesInit()
        self.scr = screen

        h, w = self.yx()

        self.lline = screen.subwin(0, 2)
        self.stline = screen.subwin(h-2, 0)
        self.stline.bkgdset(' ', color_pair(COLOR_SECONDARY) | A_REVERSE)

        self.jumpidx(self.hist.get(self.opt))
        self.render()

        if self.opt.auto:
            ungetch("\n")

        try:
            # キー入力に応じて動くメインループ
            while self.mainLoop():
                None
        finally:
            # ★ 終了時のクリーンアップ
            self.hist.cancel_timer()
            self.cache_mgr.cleanup()

        return 0

def parseArg():
    ap = argparse.ArgumentParser(description=u"""
        fadoshtui is macOS say command front ui.
        """)
    def opt(o, name, d, t, h):
        ap.add_argument(o, name, const=True, nargs='?', choices=None,
                                 default=d,  type=t,    help=h)
    opt('-r', '--rate',    1.0,  float, 'speaking speed')
    opt('-l', '--index',   None, int,   'start line index')
    opt('-c', '--context', 1,    int,   'current line margin top')
    opt('-v', '--voice',   None, str,   'say -v option')
    opt('-a', '--auto',    False,bool,  'auto start and file end auto quit')
    ap.add_argument('file', type=str, help='text file')

    return ap.parse_args();

if __name__ == "__main__":
    createConfig()
    wrapper(FadoshTUI(parseArg()).main)
