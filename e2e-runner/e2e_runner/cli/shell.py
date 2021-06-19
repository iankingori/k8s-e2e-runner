import sys

from cliff.app import App
from cliff.commandmanager import CommandManager


class E2eRunnerApp(App):

    def __init__(self):
        super(E2eRunnerApp, self).__init__(
            description='Kubernetes End-To-End Runner',
            version='1.0.0',
            command_manager=CommandManager('e2e.runner'),
            deferred_help=True,
        )


def main(argv=sys.argv[1:]):
    myapp = E2eRunnerApp()
    return myapp.run(argv)


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
