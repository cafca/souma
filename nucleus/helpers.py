import logging
from Crypto.Hash import SHA256
import os


def configure_from_args(app, args):
    app.config['NO_UI'] = args.no_ui
    app.config['LOGIN_SERVER'] = args.glia

    if args.debug is True:
        app.config["LOG_LEVEL"] = logging.DEBUG
        app.config["DEBUG"] = True
        app.logger.debug("Verbose logs active")

    if args.port is not None:
        app.config['LOCAL_PORT'] = args.port
        app.config['LOCAL_ADDRESS'] = "{}:{}".format(app.config['LOCAL_HOSTNAME'], args.port)
        app.config['SYNAPSE_PORT'] = args.port + 50
        app.config['DATABASE'] = os.path.join(app.config["USER_DATA"], 'souma_{}.db'.format(app.config["LOCAL_PORT"]))
        app.config['SQLALCHEMY_DATABASE_URI'] = "sqlite:///" + app.config['DATABASE']
        app.config["SECRET_KEY_FILE"] = os.path.join(app.config["USER_DATA"], "secret_key_{}.dat".format(args.port))
        app.config["PASSWORD_HASH_FILE"] = os.path.join(app.config["USER_DATA"], "pw_hash_{}.dat".format(args.port))

    # Must occur after lines for args.port
    if args.reset is True:
        from web_ui.helpers import reset_userdata
        reset_userdata()


def log_config_info(app):
    app.logger.info(
        "\n".join(["{:=^80}".format(" SOUMA CONFIGURATION "),
                  "{:>12}: {}".format("souma", app.config['SOUMA_ID'][:6]),
                  "{:>12}: {}".format("version", app.config['VERSION']),
                  "{:>12}: {}".format("web ui", "disabled" if app.config['NO_UI'] else app.config['LOCAL_ADDRESS']),
                  "{:>12}: {}:{}".format(
                      "synapse",
                      app.config['LOCAL_HOSTNAME'],
                      app.config['SYNAPSE_PORT']),
                  "{:>12}: {}".format("database", app.config['DATABASE']),
                  "{:>12}: {}".format("glia server", app.config['LOGIN_SERVER'])]))


def set_souma_id(app):
    # Load/set secret key
    try:
        with open(app.config["SECRET_KEY_FILE"], 'rb') as f:
            app.config['SECRET_KEY'] = f.read(24)
    except IOError:
        # Create new secret key
        app.logger.debug("Creating new secret key")
        app.config['SECRET_KEY'] = os.urandom(24)
        with open(app.config["SECRET_KEY_FILE"], 'wb') as f:
            os.chmod(app.config["SECRET_KEY_FILE"], 0700)
            f.write(app.config['SECRET_KEY'])

    # Generate ID used to identify this machine
    app.config['SOUMA_ID'] = SHA256.new(app.config['SECRET_KEY'] + str(app.config['LOCAL_PORT'])).hexdigest()[:32]

    if 'SOUMA_PASSWORD_HASH_{}'.format(app.config['LOCAL_PORT']) in os.environ:
        app.config['PASSWORD_HASH'] = os.environ['SOUMA_PASSWORD_HASH_{}'.format(app.config["LOCAL_PORT"])]
    else:
        app.config['PASSWORD_HASH'] = None
