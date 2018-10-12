from collections import OrderedDict

import graphene
from django.http import Http404
from django.shortcuts import get_object_or_404
from graphene.relay.mutation import ClientIDMutation
from graphene.types import Field, InputField
from graphene.types.mutation import MutationOptions
from graphene.types.objecttype import yank_fields_from_attrs
from graphene_django.converter import convert_django_field, convert_field_to_string
from graphene_django.registry import get_global_registry
from graphene_django.rest_framework.mutation import fields_for_serializer
from localized_fields.fields import LocalizedField

from .relay import extract_global_id

convert_django_field.register(LocalizedField, convert_field_to_string)


class SerializerMutationOptions(MutationOptions):
    lookup_field = None
    lookup_input_kwarg = None
    model_class = None
    model_operations = ["create", "update"]
    serializer_class = None
    return_field_name = None
    return_field_type = None


class SerializerMutation(ClientIDMutation):
    """
    Caluma specific SerializerMutation solving following upstream issues.

    1. Expose node instead of attributes directly.

    Dependend issues:
    https://github.com/graphql-python/graphene-django/issues/376
    https://github.com/graphql-python/graphene-django/issues/386
    https://github.com/graphql-python/graphene-django/issues/462

    2. Validation should be GraphQL errors

    https://github.com/graphql-python/graphene-django/issues/380

    Goal would be to get rid of this custom class when referenced issues
    have been resolved successfully.


    The following `Meta` attributes control the basic behavior:
    * `lookup_field`: The model field that should be used to for performing object lookup of
      individual model instances. Defaults to 'pk'.
    * `lookup_input_kwarg`: Input argument that should be used for object lookup.
      Defaults to 'lookup_field'
    * `serializer_class`: The serializer class that should be used for validating, deserializing input
      and performing side effect.
    * `model_class`: The model class to lookup instance of. Defaults to model of serializer.
    * `model_operations`: Define which operations are allowed. Defaults to `['create', 'update'].
    * `only_fields`: Restrict input fields. Defaults to serializer fields.
    * `exclude_fields`: Exclude input fields. Defaults to serializer fields.
    * `return_field_name`: Name of return graph. Defaults to camel cased model class name
    * `return_field_type`: Type of return graph. Defaults to object type of given model_class.
    """

    class Meta:
        abstract = True

    @classmethod
    def __init_subclass_with_meta__(
        cls,
        lookup_field=None,
        lookup_input_kwarg=None,
        serializer_class=None,
        model_class=None,
        model_operations=["create", "update"],
        only_fields=(),
        exclude_fields=(),
        return_field_name=None,
        return_field_type=None,
        **options
    ):
        if not serializer_class:
            raise Exception("serializer_class is required for the SerializerMutation")

        if "update" not in model_operations and "create" not in model_operations:
            raise Exception('model_operations must contain "create" and/or "update"')

        serializer = serializer_class()
        if model_class is None:
            serializer_meta = getattr(serializer_class, "Meta", None)
            if serializer_meta:
                model_class = getattr(serializer_meta, "model", None)

        if lookup_field is None and model_class:
            lookup_field = model_class._meta.pk.name
        if lookup_input_kwarg is None:
            lookup_input_kwarg = lookup_field

        input_fields = fields_for_serializer(
            serializer, only_fields, exclude_fields, is_input=True
        )

        if not return_field_name:
            model_name = model_class.__name__
            return_field_name = model_name[:1].lower() + model_name[1:]

        if not return_field_type:
            registry = get_global_registry()
            return_field_type = registry.get_type_for_model(model_class)

        output_fields = OrderedDict()
        output_fields[return_field_name] = graphene.Field(return_field_type)

        _meta = SerializerMutationOptions(cls)
        _meta.lookup_field = lookup_field
        _meta.lookup_input_kwarg = lookup_input_kwarg
        _meta.model_operations = model_operations
        _meta.serializer_class = serializer_class
        _meta.model_class = model_class
        _meta.fields = yank_fields_from_attrs(output_fields, _as=Field)
        _meta.return_field_name = return_field_name
        _meta.return_field_type = return_field_type

        input_fields = yank_fields_from_attrs(input_fields, _as=InputField)
        super(SerializerMutation, cls).__init_subclass_with_meta__(
            _meta=_meta, input_fields=input_fields, **options
        )

    @classmethod
    def get_serializer_kwargs(cls, root, info, **input):
        lookup_field = cls._meta.lookup_field
        lookup_input_kwarg = cls._meta.lookup_input_kwarg
        model_class = cls._meta.model_class
        return_field_type = cls._meta.return_field_type

        if model_class:
            if "update" in cls._meta.model_operations and lookup_input_kwarg in input:
                instance = get_object_or_404(
                    return_field_type.get_queryset(model_class.objects, info),
                    **{lookup_field: extract_global_id(input[lookup_input_kwarg])}
                )
            elif "create" in cls._meta.model_operations:
                instance = None
            else:
                raise Exception(
                    'Invalid update operation. Input parameter "{0}" required.'.format(
                        lookup_field
                    )
                )

            return {
                "instance": instance,
                "data": input,
                "context": {"request": info.context, "info": info},
            }

        return {"data": input, "context": {"request": info.context, "info": info}}

    @classmethod
    def mutate_and_get_payload(cls, root, info, **input):
        kwargs = cls.get_serializer_kwargs(root, info, **input)
        serializer = cls._meta.serializer_class(**kwargs)

        # TODO: use extensions of error to define what went wrong in validation
        # also see https://github.com/graphql-python/graphql-core/pull/204
        # potentially split each validation error into on GraphQL error
        serializer.is_valid(raise_exception=True)
        return cls.perform_mutate(serializer, info)

    @classmethod
    def perform_mutate(cls, serializer, info):
        obj = serializer.save()
        kwargs = {cls._meta.return_field_name: obj}
        return cls(**kwargs)


class UserDefinedPrimaryKeyMixin(object):
    """
    Allows a primary key to be overwritten by user.

    TODO: verify whether this makes sense to send upstream.
    """

    class Meta:
        abstract = True

    @classmethod
    def get_serializer_kwargs(cls, root, info, **input):
        lookup_field = cls._meta.lookup_field
        model_class = cls._meta.model_class
        return_field_type = cls._meta.return_field_type

        queryset = return_field_type.get_queryset(model_class.objects, info)
        filter_kwargs = {lookup_field: input[lookup_field]}
        instance = queryset.filter(**filter_kwargs).first()

        if instance is None and model_class.objects.filter(**filter_kwargs).exists():
            # disallow editing of instances which are not visible by current user
            raise Http404(
                "No %s matches the given query." % queryset.model._meta.object_name
            )

        return {
            "instance": instance,
            "data": input,
            "context": {"request": info.context, "info": info},
        }
