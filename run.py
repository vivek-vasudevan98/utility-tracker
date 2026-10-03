import os
from utility_app import create_app

app = create_app()

if __name__ == '__main__':
    # The debugger runs any code typed into its error page, so it's off unless
    # explicitly enabled (FLASK_DEBUG=1). The app only listens on this computer.
    app.run(host='127.0.0.1', debug=os.environ.get('FLASK_DEBUG') == '1')
