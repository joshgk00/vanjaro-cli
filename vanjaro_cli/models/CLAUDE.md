# Pydantic Conventions

- Use `BaseModel` for all data structures that cross API boundaries.
- Use `Field(alias="camelCase")` to map between Python snake_case and API camelCase.
- Set `model_config = {"populate_by_name": True, "extra": "allow"}` on API response models so they're resilient to new fields.
- Use `@classmethod` factory methods named `from_api()` for parsing API responses.
- Use `to_api_payload()` methods for serializing back to API format.
- Don't use Pydantic for internal-only data — a plain dataclass or dict is fine.
- When the API returns fields in inconsistent casing (e.g., `Token` vs `token`), handle this in the `from_api()` method with a comment explaining the API quirk.
