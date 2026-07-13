import os
from monitorUbi.terminal import application_context, terminal_context

os.environ["NCURSES_NO_UTF8_ACS"] = "1"
os.environ["COLORTERM"] = "truecolor"
os.environ["ESCDELAY"] = "25"

def main():
    with application_context():
        with terminal_context("xterm-256color"):
            from monitorUbi.tui import UbiApp
            
            app = UbiApp()
            app.run()

if __name__ == "__main__":
    main()
