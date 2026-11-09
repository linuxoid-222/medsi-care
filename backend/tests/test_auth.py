from unittest import TestCase

from fastapi import HTTPException

from app.auth import authenticate, get_current_user, issue_token, require_profile_access


class AuthTests(TestCase):
    def test_demo_user_token_round_trip(self) -> None:
        user = authenticate("demo-user", "demo-user")
        self.assertIsNotNone(user)
        assert user is not None
        token = issue_token(user)
        restored = get_current_user(f"Bearer {token}")
        self.assertEqual(restored.role, "user")
        require_profile_access("profile-demo", restored, write=True)

    def test_caregiver_is_read_only(self) -> None:
        caregiver = authenticate("demo-caregiver", "demo-caregiver")
        self.assertIsNotNone(caregiver)
        assert caregiver is not None
        with self.assertRaises(HTTPException) as raised:
            require_profile_access("profile-demo", caregiver, write=True)
        self.assertEqual(raised.exception.status_code, 403)

    def test_wrong_password_is_rejected(self) -> None:
        self.assertIsNone(authenticate("demo-user", "wrong"))
