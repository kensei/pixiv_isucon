#!/bin/bash
set -ex

if [ -f /var/lib/mysql/mysqld-slow.log ]; then
    sudo mv /var/lib/mysql/mysqld-slow.log /home/isucon/LOCAL/logs/mysqld-slow.log.$(date "+%Y%m%d_%H%M%S")
fi
if [ -f /var/log/nginx/isucon5.access_log.tsv ]; then
    sudo mv /var/log/nginx/isucon5.access_log.tsv /home/isucon/LOCAL/logs/isucon5.access_log.tsv.$(date "+%Y%m%d_%H%M%S")
fi
sudo systemctl restart mysql
sudo service memcached restart
sudo systemctl restart isuxi.perl
sudo systemctl restart nginx
