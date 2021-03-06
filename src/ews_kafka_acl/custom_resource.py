#  -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# Copyright 2021 John Mille<john@ews-network.net>

"""Main module."""

import uuid

from aws_cfn_custom_resource_resolve_parser import handle
from cfn_resource_provider import ResourceProvider
from compose_x_common.compose_x_common import keyisset, keypresent

from .acls_management import create_new_acls, delete_acls
from .common import LOG, differentiate_old_new_acls


class KafkaACL(ResourceProvider):
    def __init__(self):
        """
        Init method
        """
        self.cluster_info = {}
        super(KafkaACL, self).__init__()
        self.request_schema = {
            "definitions": {
                "Policy": {
                    "type": "object",
                    "required": [
                        "Resource",
                        "Principal",
                        "ResourceType",
                        "Action",
                        "Effect",
                    ],
                    "properties": {
                        "Resource": {
                            "type": "string",
                            "pattern": "^[a-zA-Z0-9_.-]+$",
                            "description": "Name of the resource to apply the ACL for",
                            "$comment": "LITERAL or PREFIX value for the resource",
                        },
                        "PatternType": {
                            "type": "string",
                            "pattern": "^[A-Z]+$",
                            "description": "Pattern type",
                            "$comment": "LITERAL or PREFIXED",
                            "enum": ["LITERAL", "PREFIXED", "MATCH"],
                            "default": "LITERAL",
                        },
                        "Principal": {
                            "type": "string",
                            "description": "Kafka user to apply the ACLs for.",
                            "$comment": "When using Confluent Kafka cloud, use the service account ID",
                        },
                        "ResourceType": {
                            "type": "string",
                            "description": "Kafka user to apply the ACLs for.",
                            "enum": [
                                "CLUSTER",
                                "DELEGATION_TOKEN",
                                "GROUP",
                                "TOPIC",
                                "TRANSACTIONAL_ID",
                            ],
                        },
                        "Action": {
                            "type": "string",
                            "description": "Access action allowed.",
                            "enum": [
                                "ALL",
                                "READ",
                                "WRITE",
                                "CREATE",
                                "DELETE",
                                "ALTER",
                                "DESCRIBE",
                                "CLUSTER_ACTION",
                                "DESCRIBE_CONFIGS",
                                "ALTER_CONFIGS",
                                "IDEMPOTENT_WRITE",
                            ],
                        },
                        "Effect": {
                            "type": "string",
                            "description": "Effect for the ACL.",
                            "$comment": "Whether you allow or deny the access",
                            "enum": ["DENY", "ALLOW"],
                        },
                        "Host": {
                            "type": "string",
                            "description": "Specify the host for the ACL. Defaults to '*'",
                            "default": "*",
                        },
                    },
                }
            },
            "properties": {
                "Policies": {
                    "type": "array",
                    "insertionOrder": False,
                    "uniqueItems": False,
                    "items": {"$ref": "#/definitions/Policy"},
                },
                "Id": {
                    "type": "string",
                    "description": "Unique ID registered for this ACL",
                    "$comment": "Generated by the system",
                },
                "BootstrapServers": {
                    "type": "string",
                    "minLength": 3,
                    "description": "Endpoint URL of the Kafka cluster in the format hostname:port",
                },
                "SecurityProtocol": {
                    "type": "string",
                    "default": "PLAINTEXT",
                    "description": "Kafka Security Protocol.",
                    "enum": ["PLAINTEXT", "SSL", "SASL_PLAINTEXT", "SASL_SSL"],
                },
                "SASLMechanism": {
                    "type": "string",
                    "default": "PLAIN",
                    "description": "Kafka SASL mechanism for Authentication",
                    "enum": [
                        "PLAIN",
                        "GSSAPI",
                        "OAUTHBEARER",
                        "SCRAM-SHA-256",
                        "SCRAM-SHA-512",
                    ],
                },
                "SASLUsername": {
                    "type": "string",
                    "default": "",
                    "description": "Kafka SASL username for Authentication",
                },
                "SASLPassword": {
                    "type": "string",
                    "default": "",
                    "description": "Kafka SASL password for Authentication",
                },
            },
            "required": ["BootstrapServers", "Policies"],
        }

    def convert_property_types(self):
        int_props = []
        boolean_props = []
        for prop in int_props:
            if keypresent(prop, self.properties) and isinstance(
                self.properties[prop], str
            ):
                self.properties[prop] = int(self.properties[prop])
        for prop in boolean_props:
            if keypresent(prop, self.properties) and isinstance(
                self.properties[prop], str
            ):
                self.properties[prop] = self.properties[prop].lower() == "true"

    def define_cluster_info(self):
        """
        Method to define the cluster information into a simple format
        """
        try:
            self.cluster_info["bootstrap_servers"] = self.get("BootstrapServers")
            self.cluster_info["security_protocol"] = self.get("SecurityProtocol")
            self.cluster_info["sasl_mechanism"] = self.get("SASLMechanism")
            self.cluster_info["sasl_plain_username"] = self.get("SASLUsername")
            self.cluster_info["sasl_plain_password"] = self.get("SASLPassword")
        except Exception as error:
            self.fail(f"Failed to get cluster information - {str(error)}")

        for key, value in self.cluster_info.items():
            if isinstance(value, str) and value.find(r"resolve:secretsmanager") >= 0:
                print("Found a resolve secrets. Trying to resolve the value")
                try:
                    self.cluster_info[key] = handle(value)
                except Exception as error:
                    LOG.error(error)
                    LOG.error("Failed to import secrets from SecretsManager")
                    self.fail(str(error))

    def create(self):
        """
        Method to create a new Kafka topic
        :return:
        """
        self.define_cluster_info()
        LOG.info(f"Connecting to {self.cluster_info['bootstrap_servers']}")
        LOG.info(f"Attempting to create new ACLs {self.get('Name')}")
        try:
            topic_name = create_new_acls(
                self.get("Policies"),
                self.cluster_info,
            )
            self.physical_resource_id = str(uuid.uuid4())
            self.set_attribute("Id", self.physical_resource_id)
            self.success(f"Created new ACLs {topic_name}")
        except Exception as error:
            self.physical_resource_id = "could-not-create"
            self.fail(f"Failed to create the ACLs. {str(error)}")

    def update(self):
        """
        :return:
        """
        self.define_cluster_info()
        old_policies = self.get_old("Policies")
        for policy in old_policies:
            if not keyisset("Host", policy):
                policy.update({"Host": "*"})
        new_policies = self.get("Policies")
        acls = differentiate_old_new_acls(new_policies, old_policies)
        LOG.info("ACLs deletion")
        LOG.info(acls[1])
        LOG.info("ACLs set")
        LOG.info(acls[0])
        try:
            delete_acls(acls[1], self.cluster_info)
        except Exception as error:
            LOG.error("Failed to delete old ACLs - Moving on")
            LOG.error(error)
            LOG.error(acls[1])
        try:
            create_new_acls(acls[0], self.cluster_info)
            self.success()
            LOG.info("Successfully created new ACLs")
        except Exception as error:
            LOG.error(error)
            LOG.error("Failed to create new ACLs")
            self.fail(str(error))

    def delete(self):
        """
        Method to delete the Topic resource
        :return:
        """
        self.define_cluster_info()
        try:
            delete_acls(self.get("Policies"), self.cluster_info)
            self.success("ACLs deleted")
        except Exception as error:
            self.fail(
                f"Failed to delete topic {self.get_attribute('Name')}. {str(error)}"
            )


def lambda_handler(event, context):
    provider = KafkaACL()
    provider.handle(event, context)
