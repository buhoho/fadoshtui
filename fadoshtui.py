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
import locale, unicodedata
import re, pickle, argparse, csv

from curses import *
from threading import Timer
from hashlib import md5
from subprocess import call, Popen, STDOUT, PIPE
from copy import copy

importlib.reload(sys)
# sys.setdefaultencoding("UTF-8") # 暫定的

locale.setlocale(locale.LC_ALL, '')
CODE     = locale.getpreferredencoding()
TMP_FILE = '/tmp/fadoshtui.cache.aiff' # format指定してもwavにすると動かない
DEVNULL  = open(os.devnull, 'w')
CONF     = os.environ['HOME'] + '/.config/fadosh'
try:
    call(['play', '--help'], stdout=DEVNULL, stderr=STDOUT)
except:
    sys.stderr.write("Error: not have play command(sox player) this enviroment\n.")
    exit(1)



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
    def __init__(self, hash, length):
        self.hash = hash
        # pickle に引き渡すファイルはリードバイナリじゃないと駄目らしい
        self.load = lambda: loadAbs(self.pkl, 'rb', pickle.load)
        self.last = None;
    def get(self, ag):
        last = (self.load() or {}).get(self.hash, 0)
        return ag.index - 1 if ag.index else last
    def set(self, idx):
        self.last and self.last.cancel()
        self.last = Timer(0.2, lambda : self._set(idx))
        self.last.start()
    def _set(self, idx):
        hist = self.load() or {}
        hist[self.hash] = idx
        with open(self.pkl, 'wb') as f:
             pickle.dump(hist, f)
        return idx

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
                       [re.compile("ー([？?！!」])"), "\1"]] 
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
    for t in open(filename, encoding="UTF-8"):
        lines.append(t.strip("\n"));
    lines.append("")
    return lines

def play(filename):
    Popen(["play", CONF + '/' + filename], stdout=DEVNULL, stderr=STDOUT);

class Serif():
    def __init__(self, close, color, pitch):
        self.close = close
        self.color = color
        self.pitch = pitch
    def txt(self, txt):
        my = copy(self)
        my.txt = txt
        return my

class SerifParser():
    # かっこ開始文字、閉じ文字、カラーID、ピッチ
    kakko = {
            None : Serif(None,  0, -140), 
            u'「': Serif(u'」', 5, -30),
            u'『': Serif(u'』', 1, 40),
            u'【': Serif(u'】', 3, 40) 
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
    say = ['say', self.rw.replace(tx)]
    if self.opt.voice:
        say += ['-v',  self.opt.voice]
    cmd = ['play', '-q', TMP_FILE, 'tempo', '-s', str(self.opt.rate), 'pitch', str(pitch)]

    call(say + ['-o', TMP_FILE]) # これが終わらないと読めないので同期処理

    return Popen(cmd, stdout=DEVNULL, stderr=STDOUT);

class FadoshTUI():
    def __init__(self, opt):
        self.st = '.'
        self.lines = loadLines(opt.file);
        self.hist  = History(f2md5(opt.file), len(self.lines))
        self.opt   = opt
        self.rw = ReplaceWord()

    def cursesInit(self):
        use_default_colors()
        init_pair(0, -1, -1)
        for i in range(16):
            init_pair(i, i, -1)
        init_pair(101, 57, 255)
        init_pair(102, 245, 255)
        init_pair(120, 198, -1)
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
                    proc and proc.poll() == None and proc.kill()
                    if c == '[':
                        i = self.index -1
                        while self.lines[i].strip() == "":
                                i -= 1
                        self.jumpidx(i-1)
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
        self.st = '>'
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
        self.st = '.'

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
        self.stline.chgat(0, 0, offset, color_pair(102))
        self.stline.refresh()

    def playSerifParse(self):
        """
        カレント行の手前の文章もパースして読み上げ位置のセリフ状態を正確に
        判定する。改行されたセリフを想定した処理
        """
        sPerser = SerifParser();
        before = 5 
        se = None;
        for idx in range(max(0, (self.index - before)), self.index + 1):
            se = sPerser.parse(self.lines[idx])
        return se

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
            self.lline.addstr(y, 0, ' ' * lx)
            # ゴミが残るので全行に行う。現在選択を示すマーカー
            self.scr.addstr(y, 0, ' ',
                            (A_REVERSE|color_pair(101) if current else 0))
            self.lline.move(y, 0)

            for seri in se:
                self.lline.addstr(seri.txt, color_pair(seri.color) | current)

        self.lline.refresh()

    # テキストの範囲に収まるようindexを相対移動
    def moveidx(self, n):
        self.index = max(0, min(len(self.lines) - 1, self.index + n))

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
        self.stline.bkgdset(' ', color_pair(101) | A_REVERSE)

        self.jumpidx(self.hist.get(self.opt))
        self.render()

        if self.opt.auto:
            ungetch("\n")

        # キー入力に応じて動くメインループ
        while self.mainLoop():
            None

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
