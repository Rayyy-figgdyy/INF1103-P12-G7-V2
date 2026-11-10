# Car Maintenance & Service Risk Tracker

INF1103 Team Project Part 2, Group 7 (P12 G7)

## Why we built this

Most car owners only know a part needs servicing when the workshop tells them,
or when something starts making a strange noise. The owner's manual tells you
how often each part should be serviced, but nobody reads a 600 page PDF.

So we built a small command line app that reads the manual for you. You pick
your car, type in a few numbers from your last workshop invoice, and the app
tells you how urgently that part needs attention, whether it's overdue, and
when you should book it in.

Our test setup has four cars: a brand new Honda City 2025, and three used
cars, a Mazda 3 Hatchback 2020, a Hyundai Elantra 2021 and a Kia Forte 2024.

You can check six parts on each car: Engine Oil, Brake Pads, Spark Plugs,
Tyres, Engine Air Filter and Coolant.

## What using it looks like

1. Register with your name, licence plate, car and COE expiry date (or log in
   if you've used it before).
2. Add the services you've had done to your maintenance history (option 1):
   the part, the date, odometer reading and action from the workshop invoice
   (inspection, replacement, or rotation for Tyres).
   You can view, edit and delete these entries too (options 2 to 4).
   Dates are always DD-MM-YYYY.
3. Choose Check a part (option 5) and pick one, for example Brake Pads. The
   app takes your last Brake Pads service from your history, so you only type
   today's odometer reading.
4. The app sends this, together with your car's manual, to the AI. The AI
   gives an urgency score from 1 to 10 and says how confident it is.
5. Our own rules then turn that into an outcome you can act on, such as
   URGENT or OK, along with a "service by" date and a risk score out of 100.

Your history shows each service with the latest urgency result next to it,
and option 6 lists the parts whose latest check needs attention. A check
drops off that list once you log a newer service for the part, so run a new
check after servicing. If an older history entry has no recorded action
(inspect, replace or rotate), the app asks you to confirm it before a check
uses it. If nothing
has changed since a check (including its date, vehicle details and brake history), the app
won't ask the AI again. It just tells you "This is repeated information" and
shows the earlier result.

### Personalised brake-pad history

With at least three valid confirmed brake-pad replacements, Python validates
the saved records and sends the confirmed replacement points to the AI. The AI
calculates the replacement-to-replacement mileage intervals itself. It then uses
that personal history together with the manufacturer's normal maintenance guidance
to produce one combined urgency score. There is no separate history urgency score.

The manufacturer's manual remains the authoritative baseline. Personal history can
add context for this specific car, but it must not be used to delay or ignore a
manufacturer-required inspection or service. If fewer than three trustworthy
replacement records are available, the AI uses the manufacturer guidance without
personalised history. Older entries without a confirmed replacement action do not
count toward the three-record requirement. Changes to eligible brake replacement
history cause the next check to be reassessed instead of reusing a stale result.


## Getting it running

### First time only (Mac)

```bash
cd INF1103-P12-G7-V2               # go into the project folder
python3 -m venv .venv              # make a virtual environment
source .venv/bin/activate          # turn it on; your prompt should now show (.venv)
pip install -r requirements.txt    # install the libraries we use
```

Next, create a file called `.env` in the project folder with your API keys:

```
GEMINI_API_KEY=your_gemini_key
GROQ_API_KEY=your_groq_key
```

You can get a free Gemini key at https://aistudio.google.com/apikey and a free
Groq key at https://console.groq.com/keys. Groq is only our backup for when
Gemini is down, so the app still runs without it. Please never commit
`.env` or paste your keys anywhere. It's already in `.gitignore`.

On Windows, use `python` instead of `python3`, `.venv\Scripts\activate`
instead of the `source` line, and create `.env` in Notepad.

Each time you open a new terminal, `cd` into the folder and run
`source .venv/bin/activate` again.

### Running the app

```bash
python main.py
```

The four manuals need to be in the `manuals` folder (they already are in the
repo). If a car's manual is missing, you won't be able to check that car's
parts.

### Running the tests

```bash
python -m pytest -v
```

The tests don't need an API key or internet. Instead of calling the AI, they
use fake, hardcoded AI answers.

### Running it in Docker (this is what we'll demo)

Open Docker Desktop first and wait until it says it's running. Then:

```bash
docker build -t car-maintenance-tracker .
docker run -it --rm --env-file .env \
  -v "$(pwd)/data:/app/data" \
  car-maintenance-tracker
```

A few things that caught us out:

1. `docker build` runs all the tests as well. If one test fails, the build fails.
2. Don't leave out `-it`. The app needs a keyboard, so without it, it exits
   straight away.
3. `--env-file .env` hands your keys to the app while it runs. The keys are
   never copied into the image.
4. `-v "$(pwd)/data:/app/data"` saves your profiles and checks on your own
   computer. Without it, everything disappears when the container stops.
5. The manuals are copied into the image when it's built, so if you change
   a PDF, build again.

On Windows PowerShell, use `${PWD}` instead of `$(pwd)`, and a backtick
`` ` `` instead of `\` at the end of each line.


## How the code is organised

We kept the four manager structure from Part 1, but every part of the app is now
a class, with one class per file. Information still flows in one direction:

```
You → IOManager → AIManager → LogicManager → DataManager
```

```
main.py                 App: builds everything and runs the menu
io_manager.py           IOManager: every print() and input()
ai_manager.py           AIManager: sends each check through the AI
logic_manager.py        LogicManager: the business rules and the outcome
data_manager.py         DataManager: gives access to the saved data

models/                 Car, PartSchedule, UserProfile
controllers/            AccountController, HistoryController, CheckController,
                        MaintenancePipeline (AI first, then the rules)
ai/                     AIProvider, GeminiProvider, GroqProvider, AIProviderFactory,
                        PromptBuilder, ResponseValidator, ManualReader
logic/                  Dates, HistoryRules, BrakeHistoryAnalyser
logic/rules/            OutcomeRule and the seven routing rules
storage/                JsonStore, Repository, JsonRepository, UserRepository,
                        ServiceHistoryRepository, CheckRepository, CarCatalogue
```

The four manager files are the only ones the rest of the app talks to, and no
manager imports another one. The `App` in main.py and the controllers connect them.

### Where to find each OOP idea

1. Classes and objects. `App.create()` builds the objects the running app uses:
   the four managers, the controllers and their helpers.
2. Encapsulation. Private attributes have two underscores (`__rules`, shown as
   `-` in UML), protected ones have one (`_client` in `AIProvider`, `#` in UML,
   because its subclasses use it). `UserProfile` uses `@property` and setters:
   the plate and car can only be read, and the name and COE date setters check
   the new value first.
3. Abstract class. `AIProvider` is abstract (Gemini is-a AIProvider). It holds
   the shared `ask()` method, and Python won't let you create one directly.
4. Inheritance. `GeminiProvider` and `GroqProvider` inherit from `AIProvider`.
   They call `super().__init__()` and override `_send()` and `EXPECTED_ERRORS`.
5. Interfaces. `Repository` (must be able to load and save records) and
   `OutcomeRule` (must be able to give an outcome) are ABC contracts.
   `JsonRepository` and the seven rules implement them.
6. Association. The controllers are handed the logged-in `UserProfile` on each
   call, use it and give it back, without keeping it.
7. Aggregation. `AIManager` is given its providers, `LogicManager` its rules and
   `App` the four managers. They exist on their own and can be swapped (the tests
   do this). A `UserProfile` is given its `Car`, which stays in the catalogue.
8. Composition. A `Car` creates its `PartSchedule` objects, `AIManager` creates
   its `PromptBuilder` and `ResponseValidator`, `GroqProvider` its `ManualReader`,
   `DataManager` its repositories and `App` its controllers. They live and die
   with their owner.
9. Polymorphism. `AIManager.ask` calls `ask()` on each provider, and
   `LogicManager.route` calls `outcome()` on each rule, without checking which
   class it is.

### Design patterns, SOLID and error handling

1. Strategy pattern. The routing rules and the AI providers are strategies:
   `LogicManager` and `AIManager` use them through one shared method.
2. Factory pattern. `AIProviderFactory.create("gemini", ...)` is the one place
   that decides how each AI provider is built.
3. Single responsibility. Each class has one job, e.g. `PromptBuilder` only
   builds prompts and `ResponseValidator` only checks replies.
4. Open/closed. A new outcome is a new `OutcomeRule` class added to the list,
   and a new AI is a new `AIProvider` subclass. Existing code doesn't change.
5. Liskov substitution. Any `AIProvider` works in `AIManager`, and any
   `Repository` works in the repositories; the tests swap in fakes.
6. Error handling. Each `except` names the errors it expects, e.g.
   `FileNotFoundError` and `json.JSONDecodeError` in `JsonStore`, and each AI
   provider lists its own `EXPECTED_ERRORS`. Input is validated before it is
   used, so these only catch real failures.

### Where to find each requirement

1. No procedural code. `tests/test_constraints.py` checks that there are no
   functions outside a class, one class per file, and that the abstract classes
   are abstract.
2. C2, AI is the core engine. `MaintenancePipeline.assess` sends every check
   through `AIManager.process` before the business rules, and the outcome
   depends on the AI's urgency score and confidence.
3. C3, structured JSON from the AI. We ask for JSON only, then
   `ResponseValidator` checks the keys, the types and that the score is
   between 1 and 10. If the answer is bad, it retries once and then falls
   back safely.
4. C4, flat-file persistence and repeat handling. Everything is stored as
   JSON in the `data` folder. Temperature 0 reduces AI response variability, and
   repeated saved checks reuse their stored result (`CheckRepository.find_repeat`).
5. C5, runs in Docker. See the `Dockerfile`. The tests run during the build.
6. C6, Git history and CI. Small commits, one feature per branch (see below).
   GitHub Actions (`.github/workflows/ci.yml`) runs the tests and the Docker
   build on every push and pull request.
7. Rule 1, the odometer can't go backwards.
   `IOManager.prompt_current_odometer` won't accept a reading lower than the
   last service or the last reading on file, and
   `HistoryRules.check_service_odometer` won't let a history entry show fewer
   km than an earlier service.
8. Rule 2, service intervals come from the manufacturer. `data/cars.json`
   holds each car's schedule, read by `CarCatalogue.get_service_interval`.
9. Rule 3, recommended service date. `LogicManager.evaluate` uses the AI's
   urgency, how fast you drive, and whether the part is safety critical
   (brake pads and tyres).
10. A rule that combines AI fields. `HighUrgencyRule`: urgency 8 or more and
    High confidence gives URGENT. The same score with lower confidence gives
    FLAGGED, so a mechanic can double check.
11. Overdue reporting. `km_overdue` and `days_overdue` are calculated
    exactly, and the AI adds a one line `overdue_summary` such as
    "Engine oil: 1,500 km overdue".
12. The AI uses the car's manual. Every request includes the car's PDF from
    the `manuals` folder, and the AI says where in the manual it found the
    answer (`manual_reference`).
13. Tests use hardcoded AI responses. See `tests/test_logic_manager.py`,
    plus tests for the other managers and `tests/test_app.py`, which runs a
    whole menu session.

### The data files

cars.json has the 4 cars, their manuals, and how often each part needs
servicing (km and months, whichever comes first). This one is in Git.

users.json has everyone's profile: name, licence plate, car and COE
expiry. The app creates it.

maintenance_history.json is each owner's service log: one entry per service
(part, performed service_action, date, odometer and an optional note), each with its own service_id so
it can be edited or deleted. The app creates it.

prompt_records.json has every AI urgency check: what was sent, what the AI
said, and what our rules decided. It is also how the app spots repeated input
and skips the AI call. The app creates it.

### When things go wrong

We wanted the app to keep going, not crash. Here's how each problem is handled:

1. Gemini is down, busy or rejects the key. `GeminiProvider` catches the
   error (one of its `EXPECTED_ERRORS`) and the same question goes to Groq,
   with the relevant parts of the manual. You still get a normal result,
   marked "Answered by: Groq (backup)".
2. Gemini and Groq both fail. The app waits a few seconds and tries once
   more, then uses safe default values. You see
   "NEEDS MANUAL REVIEW, AI assessment unavailable".
3. The AI's answer is broken or incomplete. `ResponseValidator.parse` and
   `validate` reject it. The app tries once more, then uses the safe
   default, same as above.
4. A data file is missing. `JsonStore.read` finds no file, so the app starts
   with an empty list. Your history is empty but everything else works.
5. A data file is corrupted. The JSON error is caught and logged, and the
   file is treated as empty, so the app keeps running. `JsonStore` also
   refuses to save over a corrupt file, so your data can still be repaired,
   and it writes to a temporary file first, so a failed save never leaves a
   half-written file.
6. You type something invalid. Each prompt in `io_manager` checks your
   answer, explains what's wrong and asks again.
7. A car's manual is missing. `CarCatalogue.get_manual_path` returns
   nothing, so the check doesn't start, and you're told the manual is missing.
8. Ctrl+C, or Docker run without `-it`. `App.run` catches `KeyboardInterrupt`
   or `EOFError` and exits cleanly with a goodbye message and the
   `docker run -it` hint.


## How we work together in Git

This is the workflow from the Collaboration and Git slides:

1. Get the latest `main` first: `git checkout main && git pull`
2. Make a branch for what you're working on: `git checkout -b feature/tyre-rule`
3. Commit little and often, with messages that say what changed, for example
   `add tyres to safety critical parts` (not just `update`)
4. Push it with `git push origin feature/tyre-rule`, and open a Pull Request
5. Get someone else to look at it, then merge
6. Delete the branch once it's merged


## If something isn't working

1. `command not found: pip` or `python`. Use `pip3` or `python3`, or turn
   on the venv first.
2. `API key not valid`. Open `.env` and check the line is
   `GEMINI_API_KEY=` followed by your key, with no quotes or spaces.
3. A "model not found" error. Add `GEMINI_MODEL=` plus a model name from
   AI Studio to `.env`.
4. Docker closes immediately. You probably left out `-it`.
5. Your checks vanish between Docker runs. You probably left out
   `-v "$(pwd)/data:/app/data"`.
6. `failed to connect to the docker API`. Docker Desktop isn't open. Start
   it and wait a moment.
7. Results flash past and disappear. They're still there. The app now
   waits for you to press Enter before showing the menu again.
