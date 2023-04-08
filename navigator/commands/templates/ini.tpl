# basic information
[info]
OWNER: NAV
APP_NAME: Navigator
APP_TITLE: Navigator
EMAIL_CONTACT: jlara@example.com

[ssl]
SSL: false
CERT: /etc/ssl/certs/example.com.crt
KEY: /etc/ssl/certs/example.com.key

[logging]
logname: navigator
logdir: /tmp/navigator/log/
logging_echo: true
logstash_enabled: false
logging_admin: no-reply@mobileinsight.com
logging_email: jlara@trocglobal.com
handlers: StreamHandler,ErrorFileHandler

[l18n]
language: en
country: US
language_code: en-us
localization: en_US
timezone: America/New_York

[temp]
temp_path: /tmp/navigator
