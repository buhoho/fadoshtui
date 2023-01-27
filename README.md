# FadoshTUI

[![MIT License](http://img.shields.io/badge/license-MIT-blue.svg?style=flat)](LICENSE)

macOS say command front ui. terminal text user interface.  
say command is cli base text-to-speech application.  
macOS の say コマンドのフロントUI。ターミナルで使うTUIアプリです。  
sayコマンドは音声読み上げコマンドです。FadoshTUI はセリフを強調したり  
高速で読み上げたりといった使い勝手を向上します。


## Demo

![FadoshTUI on terminal movie](http://i.imgur.com/b9f7a8y.gif)


## Features

- UTF-8 (partial) Support
- Graphical Text UI
- Very fast or slow speaking, by useing sox. (range to 0.1x - 9.0x)

## Requirement

- macOS
- sox is installed. (use play command.)
- python3 (i.e. default version in macOS)

## Install & Usage

```sh
brew install sox         # rate and pitch support require
play -nq synth 1 exp 231 # sound check
curl 'https://raw.githubusercontent.com/buhoho/fadoshtui/master/fadoshtui.py' > ~/bin/fadosh
chmod u+x ~/bin/fadosh
fadosh your-file.txt
```


## Key bindings

The key bindings in this TextUI app are similar to those in Vim.

* To quit the app, press `q`.
* To speak the text, press `Return` or `Space`.
* To scroll through the text, use `j`, `k`, `↓`, or `↑`.
* To move through pages, use `J`, `K`, `page up`, or `page down`.
* To jump to a specific index, press `:` and enter the target index number followed by `Enter`.
* To adjust the speak speed, use `h` or `l`.
* To skip to the previous or next sentence during speech, press `[` or `]`.


## Optional files.

config and history files in `~/.config/fadosh` directory.

### history.pkl file.

Automatically saved text index in this file.  
File format is simple python pickle file.

### replace.tsv file.

This replace function, is often used to read a ruby of Japanese.  
This file from is **from first column word replace to second column word**.  
It word is useing regex format on python.

一列目が変換対象の文字、二列目が変換後の文字。  
また、pythonの正規表現が使えます。

Example1:

```sh
curl 'https://raw.githubusercontent.com/buhoho/fadoshtui/master/replace.tsv' > ~/.config/fadosh/replace.tsv
open ~/.config/fadosh/replace.tsv
```

Example2:

```sh
touch ~/.config/fadosh/replace.tsv
echo "禁書目録\tインデックス" >> ~/.config/fadosh/replace.tsv
```
