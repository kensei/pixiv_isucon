#!/bin/bash
if [ -f /etc/bashrc ]; then
  . /etc/bashrc
fi

export PATH=/usr/local/bin:$PATH
export PATH=/home/isucon/.local/ruby/bin:$PATH
export PATH=/home/isucon/.local/node/bin:$PATH
export PATH=/home/isucon/.local/python3/bin:$PATH
export PATH=/home/isucon/.local/perl/bin:$PATH
export PATH=/home/isucon/.local/php/bin:$PATH
export PATH=/home/isucon/.local/php/sbin:$PATH
export PATH=/home/isucon/.local/go/bin:$PATH
export GOROOT=/home/isucon/.local/go
export GOPATH=/home/isucon/gocode
export PATH=/home/isucon/.local/scala/bin:$PATH

source $HOME/dotfiles/profile

#screen ssh-agent
if [ ! -z "${SSH_USER}" ]; then
    agent="$HOME/.ssh/.ssh-agent-$SSH_USER"
    if [ -S "$agent" ]; then
        export SSH_AUTH_SOCK=$agent
    elif [ ! -S "$SSH_AUTH_SOCK" ]; then
        export SSH_AUTH_SOCK=$agent
    elif [ ! -L "$SSH_AUTH_SOCK" ]; then
        test ! -L "$SSH_AUTH_SOCK" -a -S "$SSH_AUTH_SOCK" && ln -snf "$SSH_AUTH_SOCK" $agent
        #ln -snf "$SSH_AUTH_SOCK" $agent
        export SSH_AUTH_SOCK=$agent
    fi
fi
