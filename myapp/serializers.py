from rest_framework import serializers

from .models import Student


class StudentSerializer(serializers.ModelSerializer):
    class Meta:
        model = Student
        fields = '__all__'

    def validate_fee_total(self, value):
        if self.instance is not None and value < self.instance.paid_total:
            raise serializers.ValidationError(
                'Total fees cannot be less than payments already recorded.'
            )
        return value