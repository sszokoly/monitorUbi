import locale
import os
import sys
import termios
from contextlib import contextmanager
from typing import Any

def get_available_terminal_types():
    """
    Get list of available terminal types from the system.

    Returns:
        List of strings of available terminal types.
    """
    try:
        output = os.popen("toe -a").read().splitlines()            
        types = [line.split()[0] for line in output if line.strip()]
        return types
    except Exception:
        return []

def change_terminal(to_type="xterm-256color"):
    """
    Change the terminal type environment variable.
    
    Args:
        to_type: The terminal type to change to
        
    Returns:
        The original terminal type
    """
    old_term = os.environ.get("TERM", "")
    available_types = get_available_terminal_types()

    if to_type != old_term:
        if to_type in available_types:
            os.environ["TERM"] = to_type
            #logger.info(f"Changed terminal to '{to_type}'")
        else:
            #logger.error(f"Terminal {to_type} is not available")
            pass

    return old_term

@contextmanager
def terminal_context(term_type="xterm-256color"):
    """
    Context manager to temporarily change terminal type.
    
    Args:
        term_type: The terminal type to change to
    """
    old_term = change_terminal(term_type)
    old_locale = locale.setlocale(locale.LC_ALL, None)

    try:
        try:
            # Try using system defaults
            locale.setlocale(locale.LC_ALL, "")
        except locale.Error:
            # Fallback if SSH server doesn't have your local locale generated
            locale.setlocale(locale.LC_ALL, "en_US.UTF-8")
        yield

    finally:
        try:
            locale.setlocale(locale.LC_ALL, old_locale)
        except locale.Error as e:
            #logger.error(f"Failed to restore locale {old_locale}: {e}")
            pass

        if term_type != old_term:
            os.environ["TERM"] = old_term
            #logger.info(f"Changed terminal to '{old_term}'")

@contextmanager
def application_context():
    """
    Context manager to handle application startup and shutdown.
    
    Sets up logging, configures terminal, and ensures proper cleanup.
    """
    # Set up logging
    # loglevel = CONFIG["loglevel"].upper()

    # if loglevel not in ("NOTSET", "DISABLED", "NONE"):
    #     logging.basicConfig(
    #         format=LOG_FORMAT,
    #         filename=CONFIG["logfile"],
    #         level=loglevel
    #     )
    # else:
    #     logging.disable(logging.CRITICAL)

    # Save terminal state for restoration
    fd = sys.stdin.fileno()
    orig_term = termios.tcgetattr(fd)

    try:
        yield
    finally:
        print("Shutting down")
        try:
            termios.tcsetattr(fd, termios.TCSADRAIN, orig_term)
        except:
            pass