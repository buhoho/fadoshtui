#!/usr/bin/env python
# -*- coding: utf-8 -*-
# Copyright © https://reddit.com/u/buhoho
#
# require OSX
# require sox (sound of exchange command)
#
# fadoshtui is Mac OSX say command front ui.
# say コマンドで作成した音声をsoxを使って速度変更などの調整しながら再生する
# ついでに最後に聞いていた場所(行数)をhistoryに保存したりしたりもする

import os, os.path, time
import curses, locale, unicodedata
import re, pickle, argparse, csv
from hashlib import md5
from subprocess import call, Popen, STDOUT

locale.setlocale(locale.LC_ALL, '')
CODE = locale.getpreferredencoding()
TMP_FILE ='/tmp/fadoshtui.cache.aiff' # format指定してもwavにすると動かない
DEVNULL  = open(os.devnull, 'w')
CONF = os.environ['HOME'] + '/.fadosh'




def createConfig():
    if not os.path.isdir(CONF):
        os.mkdir(CONF)

#ファイルをロードする。コールバック無いと動かない
#ない場合、ロード失敗でFalseを返す
def loadAbs(filename, func):
    count = 4
    while count:
        try:
            with open(filename, 'r') as f:
                 return func(f)
        except IOError as e:
            return False
        except ValueError as e:
            time.sleep(.1) # 並列アクセスでコケる時がある
            count -= 1

# 最後に読んでいた位置をファイルに保存する
class History():
    pkl = CONF + '/history.pkl'
    def __init__(self, hash, length):
        self.hash = hash
        self.load = lambda: loadAbs(self.pkl, pickle.load)
    def get(self, ag):
        idx, ctx, hash = ag.index, ag.context, self.hash
        last = (self.load() or {}).get(hash, 0) - ctx
        return idx - 1 if idx else last
    def set(self, idx):
        hist = self.load() or {}
        hist[self.hash] = idx
        with open(self.pkl, 'w') as f:
             pickle.dump(hist, f)
        return idx

# TSVをロードして、その設定通りに読み上げ置換する
# 置換の適用はファイルの上から順番に行う
class ReplaceWord():
    def __init__(self):
        self.words = loadAbs(CONF + '/replace.tsv', (lambda f:
            [[re.compile(n.decode(CODE)), m]
                for (n, m) in csv.reader(f, delimiter='\t')])) or []
        # say をクラッシュさせる文字列
        self.words += [[re.compile("[ -]".decode(CODE)), ""],
                       [re.compile("-+".decode(CODE)), ""],
                       [re.compile("ー。".decode(CODE)), "ー"],
                       [re.compile("ー([？?！!」])".decode(CODE)), "\1"]] 
    # 読み替え置換
    def replace(self, txt):
        txt = txt.decode(CODE)
        for (ptn, replace) in self.words or []:
            txt = ptn.sub(replace, txt)
        return txt.decode(CODE)

def f2md5(filename):
    hasher = md5()
    with open(filename, 'rb') as f:
         hasher.update(f.read())
    return hasher.hexdigest()

def loadLines(filename):
    lines = []
    for t in open(filename):
        lines.append(t.strip("\n"));
    lines.append("")
    return lines

class SerifParser():
    # かっこ開始文字、閉じ文字、カラーID、ピッチ
    kakko = {
            None : [None , 0, -140],
            u'「': [u'」', 5, -30],
            u'『': [u'』', 1, 40],
            u'【': [u'】', 3, 40],
            }
    def __init__(self):
        # デフォルト色、ピッチ。状態が残るとマズイのでコンストラクタで初期化
        self.stack = [self.kakko[None]]
    def parse(self, line):
        lines = []
        strStack = ''
        for c in line.decode(CODE):
            strStack += c
            if self.stack[-1][0] == c: #閉じかっこ
                lines.append([strStack, self.stack[-1]])
                self.stack.pop()
                strStack = ''
            if c in self.kakko.keys(): #開始かっこ
                strStack = strStack[:-1]
                if strStack != '':
                    lines.append([strStack, self.stack[-1]])
                strStack = c
                self.stack.append(self.kakko[c])
        if strStack:
            lines.append([strStack, self.stack[-1]])
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
    for c in srcLine.decode(CODE):
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
    if not tx.strip().strip("　"):
        time.sleep(.05)
        return False # 空行を飛ばす
    say = ['say', '-o', TMP_FILE]
    if self.opt.voice:
        say += ['-v',  self.opt.voice]
    say += self.rw.replace(tx)
    call(say) # これが終わらないと読めないので同期処理
    return Popen(['play',
                  '-q', TMP_FILE, 'tempo', '-s', str(self.opt.rate),
                  'pitch', str(pitch)], stdout=DEVNULL, stderr=STDOUT);

class FadoshTUI():
    def __init__(self, opt):
        self.lines = loadLines(opt.file);
        self.hist  = History(f2md5(opt.file), len(self.lines))
        self.opt   = opt
        self.rw = ReplaceWord()
        self.counter = 0 # フレームカウンター
        curses.wrapper(self.main)

    def cursesInit(self):
        curses.use_default_colors()
        curses.init_pair(0, -1, -1)
        for i in range(0,255):
            curses.init_pair(i, i, -1)
        curses.init_pair(101, 255, 57)
        curses.init_pair(102, 255, 245)
        curses.init_pair(103, 255, 53)
        curses.curs_set(False) #カーソル非表示

    def getCmd(self):
        h, w = self.scr.getmaxyx()
        self.scr.addstr(h-1, 0, ' ' * ((self.scr.getmaxyx()[1] - 1)))
        self.scr.addstr(h-1, 0, ':')

        self.scr.nodelay(False)
        curses.curs_set(True) #カーソル表示
        curses.echo()

        s = self.scr.getstr(h-1, 1)

        curses.noecho()
        curses.curs_set(False) #カーソル非表示
        #self.scr.nodelay(True)
        return s

    def debugPrint(self, s):
        self.scr.addstr(0, 0, str(s), curses.color_pair(1) | curses.A_REVERSE)
        self.scr.nodelay(False)
        self.scr.getkey()

    # 読み上げとその間の処理を停止するループ。一部のキー入力を受け付ける
    # 読み上げ停止でFalseを返す
    def sayWaitLoop(self, line):
        parser = SerifParser()
        for tx, attr in parser.parse(line):
            proc = saycommand(self, tx, attr[2])
            while (proc and proc.poll() == None):
                self.counter += 1
                self.render()
                time.sleep(1.0 / 5)
                try:
                    c = self.scr.getkey()
                except:
                    continue
                if c == 'h' and self.opt.rate > 0.1: self.opt.rate -= 0.1
                if c == 'l' and self.opt.rate < 8.9: self.opt.rate += 0.1
                if c in " q\n":
                    proc and proc.poll() == None and proc.kill()
                    return False
        return True

    # 読み上げが終わったら次の行を読む。そんなループ
    def playLoop(self):
        self.scr.nodelay(True)
        while self.index < len(self.lines) and\
              type(self.lines[self.index]) == str:
            self.hist.set(self.index)
            self.render()
            if not self.sayWaitLoop(self.lines[self.index]):
                break
            if self.index == len(self.lines) -1:
                break
            self.moveidx(+1)
        self.scr.nodelay(False)

    def wcharSplit(self, text, offset):
        first = ""
        rest = ""
        real = 0
        wbreak = True
        for c in text.decode(CODE):
            real += min(2, len(c.encode(CODE)))
            if real == offset:
                wbreak = False
            if real <= offset:
                first += c
            else:
                rest += c
        if wbreak:
            offset -= 1
        return (first, rest, max(0, offset))

    def render(self):
        h, w = self.scr.getmaxyx()
        shift = 1 # カレント行を何行ずらして下の方で表示するか
        status = ("{0} {1:>6}/{2:<6} {3:1.2}x :".format(
                ['/', '-', '\\', '|'][self.counter % 4],
                self.index + 1,
                len(self.lines),
                self.opt.rate) +
                # ファイル名に/が入っていることを考慮していないので不完全だけど
                re.split(r"/", self.opt.file)[-1]).decode(CODE)
        self.head.addstr(0, 0, " " * w)
        ratio = float(self.index) / len(self.lines)
        ratio = (self.index + (ratio * h)) / len(self.lines)# 画面の高さ考慮
        # 比率を画面幅にマッピング
        offset = min(int(w * ratio), w)
        (first, rest, offset) = self.wcharSplit(status, offset)
        self.head.addstr(0, 0, " " * offset, curses.color_pair(102))
        self.head.addstr(0, 0, first, curses.color_pair(102))
        self.head.addstr(0, min(offset, w), rest)
        self.head.refresh()
        # 画面に描画する
        ly, lx = (h - 1, w - 2)
        try:
            self.lline.resize(ly, lx)
        except:
            ly, lx = self.lline.getmaxyx();
        vlines = []
        parser = SerifParser()
        # リフロー用に改行された文字列の配列を作る
        for y in range(0, ly - 1):
            if (len(vlines) >= ly):
                break;
            idx = self.index + y - shift
            tx  = self.lines[idx] if idx >= 0 and idx < len(self.lines) else\
                  "~" + (" " * (lx - 3)) # 範囲外は空行\
            curernt_color = curses.A_BOLD if self.index == idx else 0
            # リフロー用に改行された文字列の切り出し
            mline = getMultiLine(tx, lx-1)
            if (y < shift): # beforeコンテキストの文字はshift分切り詰める
                mline = mline[-shift:]
            for txt in mline:
                #+=だとタプルが展開されて配列要素にダイレクト挿入される
                vlines.append((txt, curernt_color))
        # 表示用の一行を描画する
        for y in range(0, ly - 1):
            txt, current = vlines[y]
            self.lline.addstr(y, 0, ' '*w)
            col = 101 if current else 0 # ゴミが残るので全行に行う
            self.scr.addstr(y + 1, 1, ' ', #現在選択を示すマーカー
                          curses.color_pair(col))
            self.lline.move(y, 0)
            for (line, attr) in parser.parse(txt):
                self.lline.addstr(line, curses.color_pair(attr[1]) | current)

        self.scr.refresh()
        self.lline.refresh()

    # 範囲を考慮して、現在のindexから相対移動
    # 実行直前に index = 0 をすれば絶対移動出来る
    def moveidx(self, n):
        self.index = max(0, min(len(self.lines) - 1,
                                self.index + n))
    # 範囲を考慮して、n行に絶対移動
    def jumpidx(self, n):
        self.index = 0
        self.moveidx(n)

    def mainLoop(self):
        # getIndex 以降のスコープではindexがNoneに汚染されるので先頭
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
        if c == 'k'   or op == curses.KEY_UP:   self.moveidx(-1)
        elif c == 'j' or op == curses.KEY_DOWN: self.moveidx(+1)
        elif op == curses.KEY_RESIZE:
            self.scr.clear()
            self.scr.refresh()
        elif c == 'K': self.moveidx(-self.scr.getmaxyx()[0]-1)
        elif c == 'J': self.moveidx(+self.scr.getmaxyx()[0]-1)
        elif c == 'h' and self.opt.rate > 0.1: self.opt.rate -= 0.1
        elif c == 'l' and self.opt.rate < 8.9: self.opt.rate += 0.1
        elif c == 'q':
            return False

        self.render()

        if c and c in " \n":
            self.playLoop();

        return True #ループ継続

    def main(self, screen):
        self.cursesInit()
        self.scr = screen
        self.head  = screen.subwin(0, 0)
        self.lline = screen.subwin(1, 2) # command line == -1
        self.jumpidx(self.hist.get(self.opt))
        self.head.bkgdset(' ', curses.color_pair(101))
        self.lline.bkgdset(' ')

        self.render()

        # キー入力に応じて動くメインループ
        while self.mainLoop():
            None

        return 0

def parseArg():
    ap = argparse.ArgumentParser(description=u"""
        fadoshtui is Mac OSX say command front ui.
        """)
    def opt(o, name, d, t, h):
        ap.add_argument(o, name, const=True, nargs='?', choices=None,
                                 default=d,  type=t,    help=h)
    opt('-r', '--rate',    1.0,  float, '読み上げ速度。')
    opt('-l', '--index',   None, int,   '再開位置(ファイルのn行目)')
    opt('-c', '--context', 0,    int,   '再開位置をc行戻す')
    opt('-v', '--voice',   None, str,   'say -v option')
    ap.add_argument('file', type=str, help='テキストファイル')

    return ap.parse_args();

if __name__ == "__main__":
    locale.setlocale(locale.LC_ALL, '')
    createConfig()
    FadoshTUI(parseArg());
