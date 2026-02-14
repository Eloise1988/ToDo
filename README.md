# Telegram To-Do Coach Bot (Python + MongoDB + ChatGPT API)

This project provides a Telegram bot that helps you manage tasks with priorities and deadlines, check in regularly on accomplishments, and coach you toward your main goal (default: making money).

## Features

- `/add` to create tasks with priority + deadline.
- `/list` to show active tasks and manage each one with buttons:
  - mark as done
  - delete
- Daily automated check-ins.
- Weekly review nudges inspired by:
  - *Getting Things Done* (capture + next actions + review)
  - *7 Habits* (goal alignment + important/not urgent)
  - *Atomic Habits* (reduce friction + consistency)
- Stale-task coaching:
  - suggests splitting tasks that remain unfinished for too long
  - flags priority misalignment with your main goal
  - suggests practical money-making moves from your recent activity context

## Stack

- Python (`python-telegram-bot`, async)
- MongoDB (task + user + journal persistence)
- OpenAI API (coaching generation)
- Designed to run on Ubuntu 20 server

## 1) Setup on Ubuntu 20

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip
```

Install MongoDB locally or use MongoDB Atlas.  
For local MongoDB, ensure it is running and reachable at your configured URI.

## 2) Create Telegram bot token

1. Open Telegram and talk to `@BotFather`.
2. Run `/newbot`.
3. Save the token.

## 3) Configure environment

```bash
cp .env.example .env
```

Edit `.env` with:

- `TELEGRAM_BOT_TOKEN`
- `MONGODB_URI`
- `OPENAI_API_KEY`

## 4) Install dependencies

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## 5) Run the bot

```bash
source .venv/bin/activate
python -m bot.main
```

## Command usage

- `/start` -> initialize profile and show help
- `/goal` -> show current main goal
- `/goal <new main goal>` -> update goal
- `/add` -> interactive add flow
- `/add <task> | <priority> | <deadline YYYY-MM-DD>` -> quick add
  - Example: `/add Build landing page | high | 2026-03-01`
- `/list` -> list active tasks with per-task action buttons
- `/checkin` -> run coaching check-in now
- `/review` -> run weekly-style review now
- `/help` -> show commands
- `/cancel` -> cancel `/add` interactive flow

## How the bot "learns" your workflow

- Any normal text message you send to the bot (not a command) is stored as a journal note.
- Use this for short updates like:
  - what you completed
  - blockers
  - what you did today
- The coaching prompt uses these notes plus your tasks to improve split-task suggestions and money-focused ideas.

Priority values accepted:

- `high`, `medium`, `low`
- `p1`, `p2`, `p3`
- `1`, `2`, `3`

Deadline values accepted:

- `YYYY-MM-DD`
- `skip` / `none` to leave empty

## Running as a systemd service

See `deploy/todo-bot.service` and replace:

- `<USER>`
- `<PROJECT_DIR>`

Then:

```bash
sudo cp deploy/todo-bot.service /etc/systemd/system/todo-bot.service
sudo systemctl daemon-reload
sudo systemctl enable --now todo-bot
sudo systemctl status todo-bot
```

## Notes

- If `OPENAI_API_KEY` is missing or API calls fail, the bot falls back to rule-based coaching.
- The bot uses UTC for scheduler times (`CHECKIN_HOUR_UTC`, `WEEKLY_REVIEW_HOUR_UTC`).
# ToDo
