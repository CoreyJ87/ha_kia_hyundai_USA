from logging import getLogger
from typing import Final

from homeassistant.components.number import (
    NumberEntity,
    NumberEntityDescription,
    NumberMode,
)
from homeassistant.const import (
    CONF_SCAN_INTERVAL,
    PERCENTAGE,
    STATE_UNAVAILABLE,
    EntityCategory,
    UnitOfTime,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from . import VehicleCoordinator, get_all_coordinators
from .const import MAX_SCAN_INTERVAL, MIN_SCAN_INTERVAL
from .vehicle_coordinator_base_entity import VehicleCoordinatorBaseEntity

_LOGGER = getLogger(__name__)

AC_CHARGING_LIMIT_KEY = "ev_charge_limits_ac"
DC_CHARGING_LIMIT_KEY = "ev_charge_limits_dc"

NUMBER_DESCRIPTIONS: Final[tuple[NumberEntityDescription, ...]] = (
    NumberEntityDescription(
        key=AC_CHARGING_LIMIT_KEY,
        name="AC Charging Limit",
        icon="mdi:ev-plug-type1",
        native_min_value=50,
        native_max_value=100,
        native_step=10,
        native_unit_of_measurement=PERCENTAGE,
        mode=NumberMode.SLIDER,
    ),
    NumberEntityDescription(
        key=DC_CHARGING_LIMIT_KEY,
        name="DC Charging Limit",
        icon="mdi:ev-plug-ccs1",
        native_min_value=50,
        native_max_value=100,
        native_step=10,
        native_unit_of_measurement=PERCENTAGE,
        mode=NumberMode.SLIDER,
    ),
)

POLL_INTERVAL_DESCRIPTION: Final = NumberEntityDescription(
    key="poll_interval",
    name="Poll Interval",
    icon="mdi:timer-sync-outline",
    native_min_value=MIN_SCAN_INTERVAL,
    native_max_value=MAX_SCAN_INTERVAL,
    native_step=1,
    native_unit_of_measurement=UnitOfTime.MINUTES,
    mode=NumberMode.BOX,
    entity_category=EntityCategory.CONFIG,
)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinators = get_all_coordinators(hass)

    entities = []
    for coordinator in coordinators.values():
        entities.append(PollIntervalNumber(coordinator, POLL_INTERVAL_DESCRIPTION))
        for description in NUMBER_DESCRIPTIONS:
            if getattr(coordinator, description.key, None) is not None:
                entities.append(
                    ChargeLimitNumber(coordinator, description)
                )

    async_add_entities(entities)


class ChargeLimitNumber(VehicleCoordinatorBaseEntity, NumberEntity, RestoreEntity):
    def __init__(
        self,
        coordinator: VehicleCoordinator,
        description: NumberEntityDescription,
    ) -> None:
        super().__init__(coordinator, description)

    @property
    def native_value(self) -> float | None:
        """Return the entity value to represent the entity state."""
        value = getattr(self.coordinator, self.entity_description.key)
        if value is None or value == 0:
            _LOGGER.debug(f"invalid value found for {self.entity_description.key} = {value}, returning stored value of {self._attr_native_value})")
            return self._attr_native_value
        else:
            self._attr_native_value = value
            return value

    async def async_set_native_value(self, value: float) -> None:
        """Set new charging limit."""
        _LOGGER.debug(f"Setting charging limit to {value} for {self.entity_description.key}")
        if (
            self.entity_description.key == AC_CHARGING_LIMIT_KEY
            and self.coordinator.ev_charge_limits_ac == int(value)
        ):
            return
        if (
            self.entity_description.key == DC_CHARGING_LIMIT_KEY
            and self.coordinator.ev_charge_limits_dc == int(value)
        ):
            return

        # set new limits
        if self.entity_description.key == AC_CHARGING_LIMIT_KEY:
            ac_limit = int(value)
            dc_limit = self.coordinator.ev_charge_limits_dc
        else:
            ac_limit = self.coordinator.ev_charge_limits_ac
            dc_limit = int(value)
        await self.coordinator.api_connection.set_charge_limits(
            vehicle_id=self.coordinator.vehicle_id,
            ac_limit=ac_limit,
            dc_limit=dc_limit,
        )
        self.coordinator.async_update_listeners()
        await self.coordinator.async_request_refresh()


    async def async_internal_added_to_hass(self) -> None:
        """Call when the button is added to hass."""
        await super().async_internal_added_to_hass()
        state = await self.async_get_last_state()
        if state is not None and state.state not in (STATE_UNAVAILABLE, None):
            self.__set_state(state.state)

    def __set_state(self, state: str | None) -> None:
        """Set the entity state."""
        # Invalidate the cache of the cached property
        self.__dict__.pop("state", None)
        self._attr_native_value = state


class PollIntervalNumber(VehicleCoordinatorBaseEntity, NumberEntity):
    """How often the vehicle status is polled, in minutes.

    This is the same setting as the scan interval in the integration
    options. Having it as an entity lets automations change it, for example
    to poll faster for a while after a drive ends.
    """

    @property
    def native_value(self) -> float | None:
        """Return the poll interval that is in use."""
        interval = self.coordinator.update_interval
        if interval is None:
            return None
        return round(interval.total_seconds() / 60)

    async def async_set_native_value(self, value: float) -> None:
        """Save the new poll interval; the update listener applies it."""
        config_entry = self.coordinator.config_entry
        self.hass.config_entries.async_update_entry(
            config_entry,
            options={**config_entry.options, CONF_SCAN_INTERVAL: int(value)},
        )
