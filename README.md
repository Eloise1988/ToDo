# Telegram To-Do Coach Bot (Python + MongoDB + ChatGPT API)

This project provides a Telegram bot that helps you manage tasks with priorities and deadlines, check in regularly on accomplishments, and coach you toward your main goal (default: making money).

## Features

- `/add` to create tasks with priority + deadline.
- `/list` to show active tasks and manage each one with buttons:
  - mark as done
  - delete
- Daily automated check-ins.
- Daily reflection prompt:
  - asks daily:
    - "Who am I?" (5-minute reflection)
    - "Need to work on lowering expectations so that I am happier."
  - stores your answer in MongoDB for future analysis/coaching
  - supports skip days via `/pass` (or `pass` / `skip`)
- Recurring weekend chores with confirmation flow:
  - Water plants every 7 days
  - Clean sheets every 21 days
  - Clean bedroom every 30 days
  - Clean bathroom every 30 days
  - Each chore is asked separately with actions: Done / Not done / Pass weekend
  - Morning weekend reminders + end-of-day confirmation prompt
  - If not done, chores keep showing on weekend days
  - If passed for weekend, they come back next weekend
- Weekly review nudges inspired by:
  - *Getting Things Done* (capture + next actions + review)
  - *7 Habits* (goal alignment + important/not urgent)
  - *Atomic Habits* (reduce friction + consistency)
- Stale-task coaching:
  - suggests splitting tasks that remain unfinished for too long
  - flags priority misalignment with your main goal
  - suggests practical money-making moves from your recent activity context
- Execution learning insights:
  - detects time-to-completion patterns
  - tracks project type tendencies
  - estimates willingness/friction from journal updates
  - flags priority/deadline conflicts
  - gives concrete improvement advice via `/improve`
- Optional bot access lock to your Telegram chat only (`ALLOWED_CHAT_ID`)

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

Preferred (your requested setup):

```bash
mkdir -p ~/.config
nano ~/.config/todo.env
```

Paste this template and fill real values:

```env
TELEGRAM_BOT_TOKEN=replace_with_botfather_token
ALLOWED_CHAT_ID=
MONGODB_URI=mongodb://127.0.0.1:27017
MONGODB_DB=todo_coach_bot
OPENAI_API_KEY=replace_with_openai_key
OPENAI_MODEL=gpt-4o-mini
CHECKIN_HOUR_UTC=16
REFLECTION_HOUR_UTC=9
CHORES_MORNING_HOUR_UTC=8
CHORES_CONFIRM_HOUR_UTC=20
WEEKLY_REVIEW_DAY=sun
WEEKLY_REVIEW_HOUR_UTC=17
STALE_TASK_DAYS=7
```

Alternative (project-local file):

```bash
cp .env.example .env
```

Edit `.env` with:

- `TELEGRAM_BOT_TOKEN`
- `MONGODB_URI`
- `OPENAI_API_KEY`

The app first looks for `~/.config/todo.env`. If it does not exist, it falls back to project `.env`.

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
- `/improve` -> detailed pattern analysis + what to improve
- `/reflect` -> ask today's reflection questions now
- `/pass` -> skip the next pending reflection question
- `/chores` -> show due recurring chores and answer each one (done / not done / pass weekend)
- `/help` -> show commands
- `/cancel` -> cancel `/add` interactive flow

## How the bot "learns" your workflow

- Any normal text message you send to the bot (not a command) is stored as a journal note.
- Use this for short updates like:
  - what you completed
  - blockers
  - what you did today
- The coaching prompt uses these notes plus your tasks to improve split-task suggestions and money-focused ideas.
- Reflection answers are also stored and reused in analysis prompts.

Priority values accepted:

- `high`, `medium`, `low`
- `p1`, `p2`, `p3`
- `1`, `2`, `3`

Deadline values accepted:

- `YYYY-MM-DD`
- `skip` / `none` to apply default deadline (+1 month)

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
- Set `ALLOWED_CHAT_ID` to lock the bot to one Telegram chat/user.
- The bot uses UTC for scheduler times (`CHECKIN_HOUR_UTC`, `REFLECTION_HOUR_UTC`, `CHORES_MORNING_HOUR_UTC`, `CHORES_CONFIRM_HOUR_UTC`, `WEEKLY_REVIEW_HOUR_UTC`).
