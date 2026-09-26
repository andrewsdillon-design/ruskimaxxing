"""One-time Stripe setup for paid cloud backup ($20/year, no trial).

Creates (or reuses) in YOUR Stripe account:
  * product "RuskiMaxxing Cloud Backup" with a $20/year price (lookup key ruskimaxxing_cloud_yearly)
  * a webhook to https://<your api domain>/stripe/webhook for the subscription events the server uses
  * a customer-portal configuration (cancel, update card, invoices) if you don't have one

Run it on the VPS after install.sh, with the secret key from Stripe Dashboard -> Developers -> API keys
(use sk_test_... first to try everything with test cards, then sk_live_...):

    sudo STRIPE_SECRET_KEY=sk_live_... /opt/ruskimaxxing-cloud/venv/bin/python \\
        /opt/ruskimaxxing-cloud/app/server/deploy/setup_stripe.py https://api.your-domain.com \\
        --write /etc/ruskimaxxing-cloud.env
    sudo systemctl restart ruskimaxxing-cloud
"""

import argparse
import os
import re
import sys
from pathlib import Path

LOOKUP_KEY = "ruskimaxxing_cloud_yearly"
PRICE_CENTS, CURRENCY = 2000, "usd"
EVENTS = ["checkout.session.completed", "customer.subscription.created", "customer.subscription.updated",
          "customer.subscription.deleted"]


def setup(stripe, api_url: str) -> dict:
    """Returns the env settings to add: STRIPE_PRICE_ID, STRIPE_WEBHOOK_SECRET (if new), STRIPE_PORTAL_CONFIG."""
    api_url = api_url.rstrip("/")
    env = {}

    prices = stripe.Price.list(lookup_keys=[LOOKUP_KEY], active=True, limit=1).data
    if prices:
        price = prices[0]
        print(f"Using existing price {price.id}")
    else:
        product = stripe.Product.create(name="RuskiMaxxing Cloud Backup",
                                        description="Cloud backup and restore for the RuskiMaxxing apps")
        price = stripe.Price.create(product=product.id, unit_amount=PRICE_CENTS, currency=CURRENCY,
                                    recurring={"interval": "year"}, lookup_key=LOOKUP_KEY)
        print(f"Created product {product.id} and $20/year price {price.id}")
    env["STRIPE_PRICE_ID"] = price.id

    hook_url = f"{api_url}/stripe/webhook"
    existing = [w for w in stripe.WebhookEndpoint.list(limit=100).data if w.url == hook_url]
    if existing:
        print(f"Webhook for {hook_url} already exists ({existing[0].id}). Its signing secret can only be read in "
              "the Stripe Dashboard (Developers -> Webhooks); keep the STRIPE_WEBHOOK_SECRET you already have.")
    else:
        hook = stripe.WebhookEndpoint.create(url=hook_url, enabled_events=EVENTS,
                                             description="RuskiMaxxing Cloud plan status")
        env["STRIPE_WEBHOOK_SECRET"] = hook.secret
        print(f"Created webhook {hook.id} -> {hook_url}")

    configs = stripe.billing_portal.Configuration.list(limit=1).data
    if configs:
        print(f"Using existing customer-portal configuration {configs[0].id}")
        env["STRIPE_PORTAL_CONFIG"] = configs[0].id
    else:
        cfg = stripe.billing_portal.Configuration.create(
            business_profile={"headline": "RuskiMaxxing Cloud Backup", "privacy_policy_url": f"{api_url}/privacy"},
            features={"invoice_history": {"enabled": True}, "payment_method_update": {"enabled": True},
                      "subscription_cancel": {"enabled": True, "mode": "at_period_end"},
                      "customer_update": {"enabled": True, "allowed_updates": ["email", "address"]}})
        env["STRIPE_PORTAL_CONFIG"] = cfg.id
        print(f"Created customer-portal configuration {cfg.id}")
    return env


def write_env(path: Path, values: dict) -> None:
    text = path.read_text() if path.exists() else ""
    for key, value in values.items():
        line = f"{key}={value}"
        if re.search(rf"^{key}=.*$", text, flags=re.M):
            text = re.sub(rf"^{key}=.*$", line, text, flags=re.M)
        else:
            text = text.rstrip("\n") + f"\n{line}\n"
    path.write_text(text)
    os.chmod(path, 0o600)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("api_url", help="your server, e.g. https://api.your-domain.com")
    parser.add_argument("--write", metavar="ENV_FILE", help="also save the settings into this env file")
    args = parser.parse_args()
    key = os.environ.get("STRIPE_SECRET_KEY")
    if not key:
        print("Set STRIPE_SECRET_KEY (Stripe Dashboard -> Developers -> API keys)", file=sys.stderr)
        return 1
    import stripe
    stripe.api_key = key
    env = setup(stripe, args.api_url)
    env["STRIPE_SECRET_KEY"] = key
    if args.write:
        write_env(Path(args.write), env)
        print(f"Saved to {args.write}. Now: sudo systemctl restart ruskimaxxing-cloud")
    else:
        print("\nAdd these to /etc/ruskimaxxing-cloud.env, then restart the service:")
        for k, v in env.items():
            print(f"{k}={v}")
    if key.startswith("sk_test_"):
        print("\nTEST MODE: pay with card 4242 4242 4242 4242, any future date, any CVC. "
              "Re-run with your sk_live_ key when you're ready to take real payments.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
