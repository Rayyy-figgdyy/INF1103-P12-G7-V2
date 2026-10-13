# INF1103 Team Project — Initial Project Details

## Project Title
**Car Maintenance & Service Risk Tracker**

## 1. Problem Statement and Target Users

Car owners may forget when individual vehicle parts were last serviced or may not know how to interpret the maintenance schedule in a long owner's manual. This can lead to maintenance being done too late, unnecessary servicing, or uncertainty about which item needs attention first.

Our application is a procedural command-line maintenance tracker that helps a car owner compare their maintenance history against the manufacturer's normal maintenance schedule and receive an AI-supported urgency assessment. The project is intentionally limited to four supported cars and six maintenance items so that the manufacturer rules can be checked and tested carefully.

Supported cars:
- Honda City 2025
- Mazda 3 Hatchback 2020
- Hyundai Elantra 2021
- Kia Forte 2024

Supported maintenance items:
- Engine Oil
- Brake Pads
- Spark Plugs
- Tyres
- Engine Air Filter
- Coolant

The intended users are owners of the supported cars who want a simple way to record maintenance history and identify which maintenance item may need attention next.

## 2. User Inputs

The user creates a profile using their name, vehicle licence plate, supported car model and COE expiry date. Maintenance history records contain the selected maintenance item, service date, service odometer reading and an optional note.

When checking a part, the application uses the latest relevant service record together with the current odometer reading. Input is validated before processing. Examples include valid date format, valid menu choices, required fields, and preventing odometer readings from moving backwards.

The application stores profiles, maintenance history and completed AI assessments in JSON files. Manufacturer maintenance intervals and the path to each owner's manual are stored in `data/cars.json`.

## 3. Use of AI

AI is the core assessment engine for each new maintenance check. The application sends the structured vehicle and maintenance information together with the relevant manufacturer manual to Gemini. Groq is used as a fallback if Gemini is unavailable.

The AI is instructed to use the manufacturer's **normal maintenance schedule** and return structured JSON containing:
- urgency score from 1 to 10
- confidence level
- overdue summary
- recommended action
- manual reference

The AI does not perform the application's final deterministic calculations. Its structured assessment is passed to `logic_manager.py`, where the program combines the AI output with the stored manufacturer interval and maintenance history.

## 4. Business Rules and Decision Logic

The application applies the following main rules after the AI response has been validated:

- Manufacturer maintenance intervals come from the selected vehicle's normal maintenance schedule stored in `cars.json` and supported by its owner manual.
- Mileage and time since the latest service are calculated to determine whether an item is due or overdue.
- First and repeat intervals are handled separately where the manufacturer specifies different values, such as engine coolant.
- Brake Pads and Tyres are treated as safety-critical maintenance items when calculating service priority.
- The AI urgency score and confidence are combined in routing decisions. For example, a high urgency score with High confidence can be routed as `URGENT`, while the same urgency with lower confidence can be `FLAGGED` for checking.
- A numeric risk score is calculated from AI urgency together with deterministic factors such as overdue status and safety criticality.
- A recommended service-by date is calculated using the maintenance interval, overdue status, current usage and urgency.
- Invalid or malformed AI responses are rejected. If both AI providers fail, the application returns a safe `NEEDS MANUAL REVIEW` outcome instead of crashing.
- Missing or corrupt JSON data files and invalid user input are handled without terminating the application.

## Architecture

The project follows the required four-manager procedural pipeline:

`User / file → io_manager.py → ai_manager.py → logic_manager.py → data_manager.py`

- `io_manager.py` — user input, validation and all terminal output
- `ai_manager.py` — prompt construction, AI API calls, JSON parsing and response validation
- `logic_manager.py` — maintenance calculations, scoring and routing rules
- `data_manager.py` — JSON persistence, vehicle schedules and history retrieval
- `main.py` — coordinates the managers and application menu flow

The codebase remains fully procedural and does not use classes.

## Repository

https://github.com/Rayyy-figgdyy/INF1103-P12-G7-V2