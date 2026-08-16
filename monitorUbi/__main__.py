from monitorUbi.logging_setup import configure_logging


def main() -> None:
    configure_logging("tui")
    from monitorUbi.tui import UbiApp

    UbiApp().run()


if __name__ == "__main__":
    main()
