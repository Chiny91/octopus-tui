<div align="center">

# 🐙 Open Octopus

> **Unofficial** open-source terminal toolkit for [Octopus Energy](https://octopus.energy) customers.
> Not affiliated with or endorsed by Octopus Energy.

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Code Style: Ruff](https://img.shields.io/badge/code%20style-ruff-000000.svg)](https://github.com/astral-sh/ruff)

</div>

---

> **Note**: This project is forked from [abracadabra50/open-octopus](https://github.com/abracadabra50/open-octopus).



**Open Octopus** is a modern, async Python client and Terminal User Interface (TUI) for tracking your Octopus Energy usage, smart rates, and dispatch schedules directly from your command line.

## ✨ Features

- **🖥️ Interactive TUI**: A beautiful dashboard in your terminal featuring live rates, usage stats, and graphs.
- **🤖 AI Assistant**: Chat with your energy data using the `octopus-ask` command (powered by Google Gemini).
- **⚡ Live Data**: Real-time power consumption monitoring (Mini/Home Pro).
- **🔋 Smart Dispatch**: View your Intelligent Octopus EV charging schedules.
- **💰 Cost Tracking**: Monthly cost projections and rate comparisons.

![Octopus TUI Screenshot](assets/screenshot.png)

## 💻 Compatibility

This tool is designed for **Unix-based systems** (Linux and macOS) as it relies on `termios` and `tty` libraries for the interactive Terminal User Interface (TUI).

**Windows users:** This application will **not** run natively on Windows. Please use [WSL (Windows Subsystem for Linux)](https://learn.microsoft.com/en-us/windows/wsl/install) to run it.

## 🚀 Installation

The easiest way to get started is using the included setup script:

```bash
# 1. Make the script executable
chmod +x run.sh

# 2. Run setup (installs dependencies and creates shortcuts)
./run.sh
```

## ⚙️ Configuration

Set your credentials via environment variables in a `.env` file or `config.txt`.

```bash
# Required: API Credentials
export OCTOPUS_API_KEY="YOUR_API_KEY_HERE"
export OCTOPUS_ACCOUNT="A-XXXXXXXX"

# Optional: Consumption Data
export OCTOPUS_MPAN="1234567890123"
export OCTOPUS_METER_SERIAL="12A3456789"

# Optional: AI Assistant (Google Gemini)
export GEMINI_API_KEY="AIxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
```

## 🛠️ Usage

After running the setup script, you can use the generated shortcuts directly:

### Terminal Dashboard (TUI)
Launch the interactive dashboard:

```bash
./octopus-tui
```

### AI Assistant
Ask questions about your energy usage in plain English (powered by Google Gemini):

```bash
./octopus-ask "What is the best time to run the washing machine today?"
./octopus-ask "How much did I use yesterday?"
```

### CLI Commands
Quick access to specific data points:

```bash
octopus rate       # Show current electricity rate
octopus account    # View account balance
octopus usage      # Fetch recent consumption data
octopus dispatch   # Check mostly recent EV dispatch slots
octopus power      # View live power draw (requires Home Mini)
```

## 📦 Supported Tariffs

- Intelligent Octopus Go
- Octopus Go
- Agile Octopus
- Flexible Octopus
- Tracker
- *And most other standard tariffs*

## 🤝 Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

1. Fork the repository
2. Create your feature branch (`git checkout -b feature/AmazingFeature`)
3. Commit your changes (`git commit -m 'Add some AmazingFeature'`)
4. Push to the branch (`git push origin feature/AmazingFeature`)
5. Open a Pull Request

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.
