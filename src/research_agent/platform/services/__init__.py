"""Operator launchers for the roles beyond storage (#315).

Each launcher reads one JSON configuration in the storage launcher's layout:
secrets are named by file reference under ``/run/secrets/``, never by value,
and the configuration names the launch profile file and the hash the
operator expects it to have. ``config.load_launch_config`` refuses a
configuration written for another role, a profile whose hash differs from
the declared one, and any declared secret that is absent, empty or readable
beyond its owner, before a launcher opens a listener or a connection.
"""
