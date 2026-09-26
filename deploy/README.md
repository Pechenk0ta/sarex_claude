# Развёртывание на сервере

Инструкция для первого запуска «Ознакомления с РД» на сервере и для последующих обновлений.
Пароли и ключи из этой инструкции никому пересылать не нужно, в том числе в чат с Claude: они живут только на сервере в файле `.env`.

Шаги делятся на две части:

- **Часть 1 — подготовка** (без консоли сервера): сервер, домен, почтовый ящик, доступ к репозиторию. Около часа, больше всего уходит на ожидание DNS.
- **Часть 2 — установка** (команды на сервере): от 30 до 60 минут.

В конце — что прислать обратно, чтобы проверить запуск, и что понадобится позже.

---

## Часть 1. Подготовка

### 1.1. Слить pull request'ы

PR идут цепочкой, каждый поверх предыдущего. Сливайте по порядку: #1 → #2 → #3 → #4 → #5 → #6 → PR этого этапа.
После каждого слияния напишите в чат — я переключу базу следующего PR на `main`.

Если нужно развернуть раньше, чем всё слито, разворачивайте ветку `stage-8-deploy`: в ней уже всё, что есть в PR #2–#6 и в этом.

### 1.2. Ключ SSH на вашем компьютере

Нужен, чтобы входить на сервер без пароля.

На Windows (PowerShell), macOS или Linux:

```bash
ssh-keygen -t ed25519 -C "ваша_почта@company.ru"
```

Нажмите Enter на все вопросы (можно задать фразу-пароль для ключа). Появятся два файла: `~/.ssh/id_ed25519` (секретный — никому не отдавать) и `~/.ssh/id_ed25519.pub` (открытый — его вставляют на сервер).

### 1.3. Сервер (VPS)

Данные хранятся в РФ, поэтому провайдер российский: Timeweb Cloud, Selectel, REG.RU или аналогичный.

При создании сервера выберите:

| Параметр | Значение |
|---|---|
| ОС | Ubuntu 24.04 LTS |
| Процессор / память / диск | 1 vCPU / 2 ГБ RAM / 20–25 ГБ SSD (1 ГБ RAM тоже хватит, но впритык) |
| Публичный IPv4 | нужен, статический |
| SSH-ключ | вставьте содержимое `id_ed25519.pub` |

Запишите IP-адрес сервера.

### 1.4. Домен

Нужен адрес вида `rd.company.ru`: по нему координаторы открывают систему, и на него ведут ссылки «Подтверждаю ознакомление» в письмах. Сертификат HTTPS выпустится сам.

У того, кто управляет DNS домена компании (или у регистратора домена), создайте запись:

| Тип | Имя | Значение |
|---|---|---|
| A | `rd` (для `rd.company.ru`) | IP сервера |

**Если домена пока нет**, можно временно использовать адрес `IP-с-дефисами.sslip.io`, например `194-67-113-53.sslip.io`: он всегда указывает на этот IP, и HTTPS для него тоже выпустится. **Только для проверки, не для рассылок:** такие адреса есть в антиспам-списках, и почтовые сервисы отклоняют письма со ссылками на них (проверено 26.09.2026: iCloud отвечает `554 5.7.1 [HM07] Message rejected due to local policy`). Когда появится домен, поменяйте `APP_DOMAIN` и `APP_BASE_URL` в `.env` и выполните `docker compose -f docker-compose.yml up -d`.

Проверка (через 5–30 минут):

```bash
nslookup rd.company.ru
```

Должен вернуться IP сервера.

### 1.5. Почтовый ящик Gmail

С этого ящика система отправляет письма подрядчикам и в него же получает их ответы. Вся переписка видна в обычном интерфейсе Gmail.

1. Создайте отдельный ящик для системы, например `rd.company@gmail.com` (лучше не личный).
2. Включите двухэтапную аутентификацию: **Аккаунт Google → Безопасность → Двухэтапная аутентификация**.
3. Создайте пароль приложения: **Аккаунт Google → Безопасность → Пароли приложений** (или поиск «Пароли приложений» в настройках аккаунта). Название — «Ознакомление с РД». Скопируйте 16-значный пароль — он показывается один раз.
4. Включите IMAP: в Gmail **Настройки → Все настройки → Пересылка и POP/IMAP → Включить IMAP → Сохранить**.

Пароль приложения понадобится на шаге 2.6, в файле `.env` на сервере.

### 1.6. Первый администратор

Решите, кто будет администратором системы (заводит проекты, корпуса, подрядчиков, пользователей). Нужны его email и ФИО — на шаге 2.8.

---

## Часть 2. Установка на сервере

Команды выполняются на сервере. Подключение с вашего компьютера:

```bash
ssh root@IP_СЕРВЕРА
```

### 2.1. Пользователь для работы и защита входа

```bash
adduser --disabled-password --gecos "" deploy
usermod -aG sudo deploy
echo "deploy ALL=(ALL) NOPASSWD:ALL" > /etc/sudoers.d/deploy
mkdir -p /home/deploy/.ssh && cp /root/.ssh/authorized_keys /home/deploy/.ssh/
chown -R deploy:deploy /home/deploy/.ssh && chmod 700 /home/deploy/.ssh && chmod 600 /home/deploy/.ssh/authorized_keys

# Только вход по ключу, root по SSH не входит
sed -i 's/^#\?PasswordAuthentication.*/PasswordAuthentication no/; s/^#\?PermitRootLogin.*/PermitRootLogin no/' /etc/ssh/sshd_config
systemctl restart ssh
```

**Не закрывайте текущее окно.** В новом окне проверьте, что вход работает:

```bash
ssh deploy@IP_СЕРВЕРА
```

Дальше всё — под пользователем `deploy`.

### 2.2. Firewall и обновления безопасности

```bash
sudo apt update && sudo apt -y upgrade
sudo apt -y install ufw unattended-upgrades git
sudo ufw allow OpenSSH
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw --force enable
sudo dpkg-reconfigure -f noninteractive unattended-upgrades
```

Порты базы данных и приложения наружу не открываются: в `docker-compose.yml` опубликованы только 80 и 443 (Caddy).

### 2.3. Docker

Пакеты из репозитория Ubuntu — без внешних источников:

```bash
sudo apt -y install docker.io docker-compose-v2
sudo usermod -aG docker deploy
```

Выйдите с сервера (`exit`) и зайдите снова, чтобы группа `docker` применилась. Проверка:

```bash
docker run --rm hello-world
```

**Если скачивание образа не работает** (Docker Hub может быть недоступен из РФ), подключите зеркало. У многих российских провайдеров есть своё — смотрите их документацию; общедоступный вариант — зеркало Google:

```bash
echo '{ "registry-mirrors": ["https://mirror.gcr.io"] }' | sudo tee /etc/docker/daemon.json
sudo systemctl restart docker
docker run --rm hello-world
```

### 2.4. Доступ сервера к репозиторию

Репозиторий закрытый, поэтому серверу нужен свой ключ только для чтения.

```bash
ssh-keygen -t ed25519 -N "" -f ~/.ssh/github_deploy -C "rd-server"
cat ~/.ssh/github_deploy.pub
cat >> ~/.ssh/config <<'EOF'
Host github.com
  IdentityFile ~/.ssh/github_deploy
  IdentitiesOnly yes
EOF
```

Скопируйте выведенную строку `ssh-ed25519 ...` и добавьте её на GitHub: репозиторий **Settings → Deploy keys → Add deploy key**, название «rd-server», галочку «Allow write access» **не** ставить.

### 2.5. Код приложения

```bash
sudo mkdir -p /opt/rd && sudo chown deploy:deploy /opt/rd
git clone git@github.com:Pechenk0ta/sarex_claude.git /opt/rd
cd /opt/rd
git checkout main          # или stage-8-deploy, если PR ещё не слиты (шаг 1.1)
```

### 2.6. Настройки (`.env`)

```bash
cd /opt/rd
cp .env.example .env
chmod 600 .env
python3 -c "import secrets; print('SECRET_KEY=' + secrets.token_urlsafe(48)); print('POSTGRES_PASSWORD=' + secrets.token_urlsafe(24))"
nano .env
```

Вставьте сгенерированные `SECRET_KEY` и `POSTGRES_PASSWORD` вместо строк с `change-me` и заполните остальное. Итоговые значения, которые нужно поменять:

```ini
APP_ENV=prod
SECRET_KEY=...                        # из команды выше
POSTGRES_PASSWORD=...                 # из команды выше
APP_DOMAIN=rd.company.ru              # домен из шага 1.4
APP_BASE_URL=https://rd.company.ru

MAIL_ADDRESS=rd.company@gmail.com     # ящик из шага 1.5
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_SSL=false
SMTP_STARTTLS=true
SMTP_AUTH=password
SMTP_PASSWORD=...                     # пароль приложения из шага 1.5 (16 символов, можно без пробелов)
```

Строку `DATABASE_URL` не трогайте: в Docker адрес базы задаётся в `docker-compose.yml`.

### 2.7. Запуск

```bash
cd /opt/rd
docker compose -f docker-compose.yml up -d --build
docker compose -f docker-compose.yml ps
```

Флаг `-f docker-compose.yml` обязателен: без него подхватятся настройки для разработки.

Все четыре сервиса (`db`, `app`, `worker`, `caddy`) должны быть в состоянии `running`, у `app` — `healthy` (через 30–60 секунд). Проверка снаружи:

```bash
curl https://rd.company.ru/health
```

Ответ: `{"status":"ok","db":"ok"}`. Если HTTPS ещё не готов, посмотрите журнал Caddy: `docker compose -f docker-compose.yml logs caddy` — обычно причина в том, что DNS-запись ещё не распространилась.

### 2.8. Первый администратор

```bash
docker compose -f docker-compose.yml exec app python -m app.scripts.create_admin admin@company.ru "Фамилия Имя Отчество"
```

Команда спросит пароль дважды (не короче 10 символов). После этого откройте `https://rd.company.ru` и войдите.

### 2.9. Пробная рассылка

1. В «Справочниках» заведите тестовый проект, корпус и подрядчика со **своим** адресом почты (не тем, что в `MAIL_ADDRESS`), привяжите подрядчика к проекту.
2. «Отправить уведомление» → любой адрес Sarex → отправить.
3. Проверьте: письмо пришло (загляните и в «Спам»), оно же есть в «Отправленных» ящика Gmail, в карточке уведомления у письма написано «Отправлено на …».
4. Нажмите в письме «Подтверждаю ознакомление» → на странице ещё раз «Подтверждаю ознакомление». На доске статус станет «Ознакомлен».
5. **Проверка plus-адреса** (важно для этапа 7): со своего ящика отправьте письмо на адрес вида `rd.company+test@gmail.com` (ваш `MAIL_ADDRESS` с `+test` перед `@`). Напишите в чат, дошло ли оно во «Входящие» ящика системы.

### 2.10. Резервные копии

Ежедневная копия базы в 03:15, хранится 14 дней:

```bash
sudo mkdir -p /var/backups/rd && sudo chown deploy:deploy /var/backups/rd
(crontab -l 2>/dev/null; echo "15 3 * * * /opt/rd/deploy/backup.sh >> /var/backups/rd/backup.log 2>&1") | crontab -
/opt/rd/deploy/backup.sh
```

**Проверка восстановления** — обязательно до начала работы (без неё неизвестно, пригодны ли копии):

```bash
/opt/rd/deploy/restore-check.sh "$(ls -t /var/backups/rd/rd-*.dump | head -1)"
```

В конце должно быть `Restore check passed.` и числа проектов и уведомлений.

Копии на том же сервере не спасают при потере сервера. Включите у провайдера автоматические снимки (бэкапы) сервера, или настройте копирование во внешнее хранилище: установите `rclone`, настройте хранилище (`rclone config`, например S3-совместимое у того же провайдера) и добавьте в строку crontab перед командой `RCLONE_REMOTE=имя:папка`.

### 2.11. Мониторинг доступности

Подключите бесплатную внешнюю проверку (например, UptimeRobot или аналог) на адрес `https://rd.company.ru/health` с оповещением на почту.

---

## Обновление до новой версии

```bash
cd /opt/rd
/opt/rd/deploy/backup.sh
git pull
docker compose -f docker-compose.yml up -d --build
docker compose -f docker-compose.yml ps
```

Миграции базы применяются автоматически при старте `app`.

**Откат**, если после обновления что-то не так:

```bash
git log --oneline -5                  # найти предыдущую версию
git checkout <хеш_предыдущей_версии>
docker compose -f docker-compose.yml up -d --build
```

Если новая версия уже изменила структуру базы, откат кода нужно согласовать с разработчиком (или восстановить базу из копии, сделанной перед обновлением).

## Полезные команды

```bash
docker compose -f docker-compose.yml logs -f app       # журнал приложения
docker compose -f docker-compose.yml logs -f worker    # журнал фоновых задач (отправка писем)
docker compose -f docker-compose.yml restart app
```

---

## Что прислать в чат после установки

Пароли и содержимое `.env` не присылайте. Нужно только:

1. Вывод `docker compose -f docker-compose.yml ps`.
2. Ответ `curl https://rd.company.ru/health`.
3. Результат пробной рассылки (шаг 2.9): дошло ли письмо, было ли в «Спаме», сработала ли кнопка.
4. Дошло ли письмо на plus-адрес (шаг 2.9, пункт 5).
5. Итог `restore-check.sh` (шаг 2.10).
6. Если что-то пошло не так — команду и её вывод целиком.

## Что понадобится позже (не для запуска)

**Для этапа 7 — разбор ответов моделью Qwen3.5 Flash:** аккаунт у провайдера, через которого подключаем модель, и ключ API. Ключ вписывается только в `.env` на сервере (`LLM_API_KEY`).

**Решение по полю «название комплекта».** Сейчас столбцы доски подписаны хвостом ссылки Sarex (`KZH1-rev2`). Можно добавить в форму отправки необязательное поле «Название комплекта» (например, «КЖ.1 изм. 2») — тогда доска будет выглядеть как на макете.
