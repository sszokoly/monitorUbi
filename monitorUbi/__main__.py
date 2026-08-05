import os
from monitorUbi.logging_setup import configure_logging
from monitorUbi.terminal import application_context, terminal_context


def main():
    configure_logging("tui")
    with application_context():
        with terminal_context("xterm-256color"):
            from monitorUbi.tui import UbiApp
            
            app = UbiApp()
            app.run()

if __name__ == "__main__":
    main()
