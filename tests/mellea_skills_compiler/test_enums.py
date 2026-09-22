from mellea_skills_compiler.enums import PiMessageType


class TestPiMessageType:
    """Test PiMessageType enum values match pi's --mode json event schema."""

    def test_values(self):
        assert PiMessageType.SESSION == "session"
        assert PiMessageType.AGENT_START == "agent_start"
        assert PiMessageType.TURN_START == "turn_start"
        assert PiMessageType.MESSAGE_START == "message_start"
        assert PiMessageType.MESSAGE_UPDATE == "message_update"
        assert PiMessageType.MESSAGE_END == "message_end"
        assert PiMessageType.TURN_END == "turn_end"
        assert PiMessageType.AGENT_END == "agent_end"
        assert PiMessageType.AGENT_SETTLED == "agent_settled"
