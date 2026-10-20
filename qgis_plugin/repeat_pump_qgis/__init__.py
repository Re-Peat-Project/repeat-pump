def classFactory(iface):
    from .plugin import RepeatPumpPlugin
    return RepeatPumpPlugin(iface)
