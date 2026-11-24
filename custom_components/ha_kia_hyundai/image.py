from datetime import datetime
from logging import getLogger

from homeassistant.components.image import ImageEntity, ImageEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import dt as dt_util

from . import get_all_coordinators
from .vehicle_coordinator import VehicleCoordinator
from .vehicle_coordinator_base_entity import VehicleCoordinatorBaseEntity

_LOGGER = getLogger(__name__)
PARALLEL_UPDATES: int = 1


async def async_setup_entry(
    hass: HomeAssistant, config_entry: ConfigEntry, async_add_entities: AddEntitiesCallback
):
    coordinators = get_all_coordinators(hass)

    entities = []
    for coordinator in coordinators.values():
        if coordinator.surround_view_supported:
            entities.append(SurroundViewImage(hass, coordinator))

    async_add_entities(entities)


def _captured_at(capture: dict | None) -> datetime | None:
    """Return when a capture was taken.

    Genesis reports the time as YYYYMMDDHHMMSS in vehicle local time, which is
    taken to be the Home Assistant time zone.
    """
    if not capture or not capture.get("captured_at"):
        return None
    try:
        captured = datetime.strptime(capture["captured_at"], "%Y%m%d%H%M%S")
    except ValueError:
        return None
    return captured.replace(tzinfo=dt_util.DEFAULT_TIME_ZONE)


class SurroundViewImage(VehicleCoordinatorBaseEntity, ImageEntity):
    """The newest surround view capture: four cameras and the top-down view."""

    _attr_content_type = "image/jpeg"

    def __init__(self, hass: HomeAssistant, coordinator: VehicleCoordinator):
        super().__init__(coordinator, ImageEntityDescription(
            key="surround_view",
            name="Surround View",
            icon="mdi:car-parking-lights",
        ))
        ImageEntity.__init__(self, hass)
        self._attr_image_last_updated = _captured_at(coordinator.surround_view)

    @callback
    def _handle_coordinator_update(self) -> None:
        self._attr_image_last_updated = _captured_at(self.coordinator.surround_view)
        super()._handle_coordinator_update()

    async def async_image(self) -> bytes | None:
        capture = self.coordinator.surround_view
        return capture["image"] if capture else None
