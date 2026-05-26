from shared.models.fleet_tree import ROLE_PERMISSIONS, RoleName
from shared.models.fleet_tree_codec import decode_fleet_tree, encode_fleet_tree
from shared.models.fleet_tree_factory import build_default_fleet_tree


def test_role_permissions_exist() -> None:
    assert ROLE_PERMISSIONS[RoleName.COMMANDER].ch1.tx is True
    assert ROLE_PERMISSIONS[RoleName.SOLDIER].ch2.rx is False


def test_fleet_tree_codec_roundtrip() -> None:
    model = build_default_fleet_tree()
    text = encode_fleet_tree(model)
    rebuilt = decode_fleet_tree(text)
    assert rebuilt.fleets[0].name == "Fleet1"
    assert rebuilt.fleets[0].wings[0].squads[0].role_slots[0].role == RoleName.COMMANDER


def test_legacy_sergeant_role_is_normalized_to_pilot() -> None:
    rebuilt = decode_fleet_tree(
        """
        {
          "fleets": [
            {
              "fleet_id": "fleet_1",
              "name": "Fleet1",
              "wings": [
                {
                  "wing_id": "wing_1",
                  "name": "Wing1",
                  "squads": [
                    {
                      "squad_id": "squad_1",
                      "name": "Squad1",
                      "role_slots": [
                        {
                          "slot_id": "squad_1_sergeant",
                          "role": "Sergeant"
                        }
                      ]
                    }
                  ]
                }
              ]
            }
          ]
        }
        """
    )
    slot = rebuilt.fleets[0].wings[0].squads[0].role_slots[0]
    assert slot.role == RoleName.PILOT
    assert slot.slot_id == "squad_1_pilot"


def test_slot_custom_name_roundtrip_and_display_name() -> None:
    rebuilt = decode_fleet_tree(
        """
        {
          "fleets": [
            {
              "fleet_id": "fleet_1",
              "name": "Fleet1",
              "wings": [
                {
                  "wing_id": "wing_1",
                  "name": "Wing1",
                  "squads": [
                    {
                      "squad_id": "squad_1",
                      "name": "Squad1",
                      "role_slots": [
                        {
                          "slot_id": "slot_alpha",
                          "role": "Pilot",
                          "custom_name": "Alpha Lead"
                        }
                      ]
                    }
                  ]
                }
              ]
            }
          ]
        }
        """
    )
    slot = rebuilt.fleets[0].wings[0].squads[0].role_slots[0]
    assert slot.custom_name == "Alpha Lead"
    assert slot.display_name == "Alpha Lead"

    slot.occupant_callsign = "Viper"
    assert slot.display_name == "Alpha Lead [Viper]"

    encoded = encode_fleet_tree(rebuilt)
    assert '"custom_name": "Alpha Lead"' in encoded
