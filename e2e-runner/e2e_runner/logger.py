import logging


def get_logger(name=None):
    logger = logging.getLogger(name)

    st = logging.StreamHandler()

    formatter = logging.Formatter(
        '%(asctime)s %(levelname)s %(name)s: %(message)s',
        datefmt='%m/%d/%Y %I:%M:%S %p')
    st.setFormatter(formatter)

    logger.addHandler(st)
    logger.setLevel(logging.DEBUG)
    logger.propagate = False

    return logger
